# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import json
import logging
import tomllib
from collections.abc import Iterator, Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import (
    Any,
)

from .core.format import ruff_installed
from .core.loader import CollectionError, RuleName
from .core.loader import collect_rules as collect_core_rules
from .core.loader import load as load_core_rules
from .core.rule import Rule
from .ftypes import (
    Config,
    Formatter,
    Options,
    OutputFormat,
    QualifiedRule,
    QualifiedRuleRegex,
    RawConfig,
)
from .template import template_error

TUKUROI_CONFIG_FILENAMES = ("tukuroi.toml", ".tukuroi.toml", "pyproject.toml")


log = logging.getLogger(__name__)


class ConfigError(ValueError):
    """
    A config that tukuroi cannot use. ``path`` is the file, when the error is in
    one: that of ``config``, or a file that is not TOML.
    """

    def __init__(
        self,
        msg: str,
        config: RawConfig | None = None,
        *,
        path: Path | None = None,
    ) -> None:
        super().__init__(msg)
        self.config = config
        self.path = config.path if config else path

    def describe(self) -> str:
        """
        The message after the path of the file, relative to the current
        directory if it is under it: how the CLI shows the error (#40).
        """
        if self.path is None:
            return str(self)
        try:
            shown = self.path.relative_to(Path.cwd())
        except ValueError:
            shown = self.path
        return f"{shown}: {self}"


class RulesOptionError(ConfigError):
    """
    A rule of ``--rules`` (:attr:`Options.rules`) that cannot be loaded. The
    CLI makes it a usage error of the option (#40).
    """

    def describe(self) -> str:
        return f"--rules: {self}"


def log_skipped(rule: QualifiedRule) -> None:
    """Warn that ``rule``, a custom rule, is not imported."""
    log.warning(f"Skipped rules '{rule}': custom rules are turned off")


def load_rules(config: Config) -> tuple[type[Rule], ...]:
    """
    The rules that ``config`` enables, sorted by name: the built-in rules in
    ``tukuroi.rules``, and the custom rules. A rule that cannot be loaded is a
    :class:`ConfigError` (#40), without the config that names it: see
    :func:`check_rules` for that.
    """
    try:
        return collect_core_rules(
            [rule_name(rule) for rule in config.enable],
            [rule_name(rule) for rule in config.disable],
            root_import=root_import_of(config),
            custom_rules=config.custom_rules,
        )
    except CollectionError as error:
        raise ConfigError(str(error)) from error


def root_import_of(config: Config) -> Path | None:
    """The path that ``enable-root-import`` of ``config`` puts on ``sys.path``."""
    if not config.enable_root_import:
        return None
    if isinstance(config.enable_root_import, Path):
        return config.root / config.enable_root_import
    return config.root


# The configs, and the names of --rules, whose rules were loaded in this
# process, with how: each is checked once (#40).
_CHECKED: set[tuple[object, ...]] = set()


def check_rules(
    raw_configs: Sequence[RawConfig], config: Config, options: Options | None = None
) -> None:
    """
    Load the rules that each of ``raw_configs``, the configs merged into
    ``config``, names, from the root config inward, and the first one that
    cannot be loaded raises a :class:`ConfigError` that names the key (#40).
    The rules of all the overrides are loaded, whether or not they apply to the
    file. With ``--rules``, only its rules are loaded, and the error is a
    :class:`RulesOptionError`. The rules skipped with custom rules turned off
    are not loaded.
    """
    root_import = root_import_of(config)
    how = (root_import, config.custom_rules)
    if options and options.rules:
        if (*how, tuple(options.rules)) not in _CHECKED:
            for rule in options.rules:
                if error := load_error(rule, config):
                    raise RulesOptionError(error)
            _CHECKED.add((*how, tuple(options.rules)))
        return
    for raw in reversed(raw_configs):
        if (*how, raw.path, repr(raw.data)) in _CHECKED:
            continue
        for key, names in named_rules(raw.data):
            for name in names:
                rule = parse_rule(name, raw.path.parent, raw)
                if error := load_error(rule, config):
                    raise ConfigError(f"{key}: {error}", config=raw)
        _CHECKED.add((*how, raw.path, repr(raw.data)))


def load_error(rule: QualifiedRule, config: Config) -> str | None:
    """Why the rules of ``rule`` cannot be loaded for ``config``, if they cannot."""
    if not config.custom_rules:
        if not rule.builtin:
            return None
        root_import = None  # As collect_rules: for custom rules only.
    else:
        root_import = root_import_of(config)
    try:
        load_core_rules(rule_name(rule), root_import)
    except CollectionError as error:
        return str(error)
    return None


def named_rules(data: dict[str, Any]) -> Iterator[tuple[str, list[str]]]:
    """
    The rules that ``data``, the table ``[tool.tukuroi]`` of a config, names, in
    the order of the file: by key, with the override before the key in one.
    """
    for key, value in data.items():
        if key in ("enable", "disable"):
            yield key, value
        elif key == "overrides":
            for override in value:
                where = override_where(override["path"])
                for name, rules in override.items():
                    if name in ("enable", "disable"):
                        yield where + name, rules


def rule_name(rule: QualifiedRule) -> RuleName:
    """
    ``rule`` as the new engine names it: with the directory, made absolute, only
    for a local rule. ``validate-config`` gives the directory of its path as is.
    """
    root = rule.root.resolve() if rule.local and rule.root else None
    return RuleName(rule.module, rule.name, root)


# What marks the root of a repository: the search for configs stops there (#13).
# .git is a file in a worktree and in a submodule.
REPOSITORY_MARKERS = (".git", ".hg")


def search_root(directory: Path) -> Path:
    """
    Where the search for the configs of ``directory`` stops at the latest (#13):
    the nearest root of a repository, a directory with one of
    :data:`REPOSITORY_MARKERS`. Outside a repository, the current directory if
    ``directory`` is in it, or else ``directory`` itself. A config above it, which
    someone else may have put there, is not read.
    """
    for parent in (directory, *directory.parents):
        if any((parent / marker).exists() for marker in REPOSITORY_MARKERS):
            return parent
    cwd = Path.cwd().resolve()
    return cwd if directory.is_relative_to(cwd) else directory


def locate_configs(path: Path, root: Path | None = None) -> list[Path]:
    """
    Given a file path, locate all relevant config files in priority order.

    Walking upward from target path, creates a list of candidate paths that exist
    on disk, ordered from nearest/highest priority to further/lowest priority.

    If root is given, only return configs between path and root (inclusive), ignoring
    any paths outside of root, even if they would contain relevant configs.
    If given, root must contain path. Without it, the search stops at
    :func:`search_root` (#13).

    Returns a list of config paths in priority order, from highest priority to lowest.
    """
    results: list[Path] = []

    if not path.is_dir():
        path = path.parent

    root = root.resolve() if root is not None else search_root(path.resolve())
    path = path.resolve()
    path.relative_to(root)  # enforce path being inside root

    while True:
        candidates = (path / filename for filename in TUKUROI_CONFIG_FILENAMES)
        for candidate in candidates:
            if candidate.is_file():
                results.append(candidate)

        if path == root or path == path.parent:
            break

        path = path.parent

    return results


def read_configs(paths: list[Path]) -> list[RawConfig]:
    """
    Read config data for each path given, and return their raw toml config values.

    Skips any path with no — or empty — `tool.tukuroi` section.
    Stops early at any config with `root = true`.

    Maintains the same order as given in paths, minus any skipped files.
    A file that is not TOML is a :class:`ConfigError`, with the message of
    :mod:`tomllib`, as is the first value of a config that tukuroi cannot use
    (see :func:`value_errors`).
    """
    configs: list[RawConfig] = []

    for path in paths:
        path = path.resolve()
        content = path.read_text()
        try:
            data = tomllib.loads(content)
        except tomllib.TOMLDecodeError as error:
            raise ConfigError(str(error), path=path) from error
        outside = path.name in ("tukuroi.toml", ".tukuroi.toml")
        if outside and (error := next(outside_errors(data), None)):
            raise ConfigError(error, path=path)
        tukuroi_data = table(data, "tool", path).get("tukuroi", {})
        if not isinstance(tukuroi_data, dict):
            raise ConfigError(
                must_be("tool.tukuroi", "a table", tukuroi_data), path=path
            )

        if tukuroi_data:
            config = RawConfig(path=path, data=tukuroi_data)
            if (error := next(value_errors(config.data), None)) is not None:
                raise ConfigError(error, config=config)
            configs.append(config)

            if config.data.get("root", False):
                break

    return configs


def outside_errors(data: dict[str, Any]) -> Iterator[str]:
    """
    The keys of ``data``, a tukuroi.toml or .tukuroi.toml, outside [tool.tukuroi],
    where tukuroi does not read them (#40). A pyproject.toml has the keys of
    other tools there, and so may a file of another name (--config-file).
    """
    for key, value in data.items():
        if key != "tool" or not isinstance(value, dict):
            yield f"{key}: must be under [tool.tukuroi]"
            continue
        for name in value:
            if name != "tukuroi":
                yield f"tool.{name}: must be under [tool.tukuroi]"


def table(data: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    """The table ``key`` of ``data``, read from ``path``: empty if there is none."""
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(must_be(key, "a table", value), path=path)
    return value


def toml_type(value: object) -> str:
    """
    The type of ``value``, a value that :mod:`tomllib` reads, as TOML v1.1.0
    names it, with an article (#40).
    """
    match value:
        case bool():
            return "a boolean"
        case int():
            return "an integer"
        case float():
            return "a float"
        case str():
            return "a string"
        # Before date: a datetime is a date too.
        case datetime() if value.tzinfo is not None:
            return "an offset date-time"
        case datetime():
            return "a local date-time"
        case date():
            return "a local date"
        case time():
            return "a local time"
        case list():
            return "an array"
        case dict():
            return "a table"
    raise AssertionError(f"not a value that tomllib reads: {value!r}")


def must_be(key: str, expected: str, value: object) -> str:
    """The message for ``value`` of ``key``, which is not ``expected``."""
    return f"{key}: must be {expected}, got {toml_type(value)}"


RULES = "an array of strings"
OVERRIDES = "an array of tables ([[tool.tukuroi.overrides]])"
# The keys of [tool.tukuroi], of an override, and the keys that #21 removed: any
# other key is an error (#40).
KEYS = (
    "disable",
    "enable",
    "enable-root-import",
    "formatter",
    "output-format",
    "output-template",
    "overrides",
    "root",
)
OVERRIDE_KEYS = ("disable", "enable", "formatter", "path")
REMOVED_KEYS = ("options", "python-version", "tags")
# What formats a fixed file (#108): nothing, or ruff format.
FORMATTERS = {f.value: f for f in Formatter}
# In any case, as the option (#40).
OUTPUT_FORMATS = {o.value: o for o in OutputFormat}


def value_errors(data: dict[str, Any]) -> Iterator[str]:
    """
    The messages for the values in ``data``, the table ``[tool.tukuroi]`` of a
    config, that tukuroi cannot use: a value of the wrong type, or a rule name that
    is not valid (#40). The keys are checked in their order in the file, and
    each message starts with the key.

    All the overrides are checked, whether or not they apply to the file that is
    linted. A key that is not one of :data:`KEYS` is an error. Whether a rule can
    be imported is not checked, nor ``enable-root-import`` in a config that is
    not the root.
    """
    for key, value in data.items():
        match key:
            case "root":
                if not isinstance(value, bool):
                    yield must_be(key, "a boolean", value)
            case "enable" | "disable":
                yield from rule_errors(key, value)
            case "enable-root-import":
                yield from root_import_errors(value)
            case "formatter":
                yield from formatter_errors(value)
            case "output-format":
                yield from output_format_errors(value)
            case "output-template":
                if not isinstance(value, str):
                    yield must_be(key, "a string", value)
                elif error := template_error(value):
                    yield f"{key}: {error}"
            case "overrides":
                yield from override_errors(value)
            case _:
                yield key_error(key, KEYS)


def key_error(key: str, keys: Sequence[str]) -> str:
    """The message for ``key``, which is not one of ``keys``."""
    if key in REMOVED_KEYS:
        return f"{key}: no longer supported"
    return f"{key}: unknown key, not one of {', '.join(map(repr, keys))}"


def rule_errors(key: str, value: object) -> Iterator[str]:
    """The messages for ``value``, the rules of ``key``: names in an array."""
    if not isinstance(value, list):
        yield must_be(key, RULES, value)
        return
    for rule in value:
        if not isinstance(rule, str):
            yield f"{key}: must be {RULES}, got an array with {toml_type(rule)}"
            return
        if not QualifiedRuleRegex.match(rule):
            yield f"{key}: invalid rule name {rule!r}"


def root_import_errors(value: object) -> Iterator[str]:
    """The messages for ``value`` of ``enable-root-import``."""
    if isinstance(value, bool):
        return
    if not isinstance(value, str) or value == "":
        got = "an empty string" if value == "" else toml_type(value)
        yield f"enable-root-import: must be a boolean or a relative path, got {got}"
    elif Path(value).is_absolute():
        yield "enable-root-import: absolute paths not allowed"
    elif ".." in Path(value).parts:
        yield "enable-root-import: '..' components not allowed"


def formatter_errors(value: object) -> Iterator[str]:
    """
    The messages for ``value`` of ``formatter``: one of :data:`FORMATTERS`, and
    ``"ruff"`` only with the optional ruff package installed (#108).
    """
    if not isinstance(value, str):
        yield must_be("formatter", "a string", value)
    elif value not in FORMATTERS:
        choices = ", ".join(map(repr, FORMATTERS))
        yield f"formatter: unknown value {value!r}, not one of {choices}"
    elif FORMATTERS[value] is Formatter.ruff and not ruff_installed():
        yield 'formatter: "ruff" needs the ruff package: pip install "tukuroi[ruff]"'


def output_format_errors(value: object) -> Iterator[str]:
    """The messages for ``value`` of ``output-format``: an empty string is unset."""
    if not isinstance(value, str):
        yield must_be("output-format", "a string", value)
    elif value and value.lower() not in OUTPUT_FORMATS:
        choices = ", ".join(map(repr, OUTPUT_FORMATS))
        yield f"output-format: unknown value {value!r}, not one of {choices}"


def override_errors(value: object) -> Iterator[str]:
    """
    The messages for ``value`` of ``overrides``. The message for an override
    shows its ``path``, as TOML writes it.
    """
    if not isinstance(value, list):
        yield must_be("overrides", OVERRIDES, value)
        return
    for override in value:
        if not isinstance(override, dict):
            yield f"overrides: must be {OVERRIDES}, got an array with {toml_type(override)}"
            return
        if "path" not in override:
            yield "overrides: a table has no path"
            return
        path = override["path"]
        if not isinstance(path, str):
            yield must_be("overrides: path", "a string", path)
            return
        if path == "":
            yield "overrides: path: must not be an empty string"
            return
        where = override_where(path)
        for key, rules in override.items():
            if key in ("enable", "disable"):
                yield from (where + error for error in rule_errors(key, rules))
            elif key == "formatter":
                yield from (where + error for error in formatter_errors(rules))
            elif key in KEYS:
                yield f"{where}{key}: not allowed in an override"
            elif key != "path":
                yield where + key_error(key, OVERRIDE_KEYS)


def override_where(path: str) -> str:
    """The start of a message about the override of ``path``, as TOML writes it."""
    # A JSON string is a TOML basic string.
    return f"overrides (path = {json.dumps(path, ensure_ascii=False)}): "


def parse_rule(rule: str, root: Path, config: RawConfig | None = None) -> QualifiedRule:
    """
    Given a raw rule string, parse and return a QualifiedRule object
    """
    if not (match := QualifiedRuleRegex.match(rule)):
        raise ConfigError(f"invalid rule name {rule!r}", config=config)

    group = match.groupdict()
    module = group["module"]
    name = group["name"]
    local = group["local"]

    if local:
        return QualifiedRule(module, name, local, root)
    else:
        return QualifiedRule(module, name)


def merge_configs(
    path: Path,
    raw_configs: list[RawConfig],
    root: Path | None = None,
    *,
    config_file: bool = False,
) -> Config:
    """
    Given multiple raw configs, merge them in priority order.

    Assumes raw_configs are given in order from highest to lowest priority.
    Their levels (see :func:`levels`) are merged from the farthest to the
    nearest, and a nearer level wins (#40): the rules that it names take the
    place of the same rules in the farther levels (see :func:`contains`). With
    ``config_file``, ``raw_configs`` is the config of ``--config-file``.
    """

    enable_root_import: bool | Path = Config.enable_root_import
    enable_rules: set[QualifiedRule] = {QualifiedRule("tukuroi.rules")}
    disable_rules: set[QualifiedRule] = set()
    output_format: OutputFormat = OutputFormat.fixit
    output_template: str = ""
    formatter: Formatter = Formatter.none

    for config in reversed(raw_configs):
        if root is None:
            root = config.path.parent

        data = config.data
        if data.get("root", False):
            root = config.path.parent

        # The values are checked as the config is read (read_configs), but where
        # the root is depends on the configs that are merged.
        if value := data.get("enable-root-import", False):
            if root != config.path.parent:
                raise ConfigError(
                    "enable-root-import: only allowed in a root config", config=config
                )
            enable_root_import = Path(value) if isinstance(value, str) else True

        if value := data.get("output-format", ""):
            output_format = OUTPUT_FORMATS[value.lower()]

        if value := data.get("output-template", ""):
            output_template = value

        directory = config.path.parent
        for level in levels(path, config, config_file=config_file):
            # The nearest level that names a formatter wins (#108).
            if "formatter" in level:
                formatter = FORMATTERS[level["formatter"]]
            disable = {
                parse_rule(r, directory, config) for r in level.get("disable", ())
            }
            # A name in both: `disable` wins.
            enable = {parse_rule(r, directory, config) for r in level.get("enable", ())}
            enable -= disable
            enable_rules -= {
                r for r in enable_rules if any(contains(d, r) for d in disable)
            }
            disable_rules -= {
                r for r in disable_rules if any(contains(e, r) for e in enable)
            }
            enable_rules |= enable
            disable_rules |= disable

    return Config(
        path=path,
        root=root or Path(path.anchor),
        enable_root_import=enable_root_import,
        enable=sorted(enable_rules),
        disable=sorted(disable_rules),
        formatter=formatter,
        output_format=output_format,
        output_template=output_template,
    )


def levels(
    path: Path, config: RawConfig, *, config_file: bool = False
) -> Iterator[dict[str, Any]]:
    """
    The tables of ``config`` that apply to ``path``, each a level of the
    hierarchy, from the farthest to the nearest (#40): the top level, then the
    overrides, the shallowest path first, and in the order of the file for the
    same depth. The top level of the config of ``--config-file``
    (``config_file``) applies to ``path`` wherever it is; the paths of its
    overrides are in the directory of the config, as in any other.
    """
    directory = config.path.parent.resolve()
    if config_file or path.is_relative_to(directory):
        yield config.data
    overrides = []
    for override in config.data.get("overrides", ()):
        subpath = (directory / override["path"]).resolve()
        if path.is_relative_to(subpath):
            overrides.append((len(subpath.parts), override))
    # sorted() is stable: the order of the file stays for the same depth.
    for _, override in sorted(overrides, key=lambda item: item[0]):
        yield override


def contains(name: QualifiedRule, other: QualifiedRule) -> bool:
    """
    Whether ``name`` gives the rules of ``other``, by the names alone (#40):
    ``other`` is ``name``, or ``name`` is a module and ``other`` is the module,
    a module in it, or a rule of one of them. A module in it is one level down,
    as the rules of a package are its own and those of its modules. A rule named
    by another module, as a package names the rules of its modules
    (``tukuroi.rules:NoStaticIfCondition``), is not told apart.
    """
    if name.root != other.root:
        return False
    if name.name is not None:
        return name == other
    return name.module in (other.module, other.module.rpartition(".")[0])


def generate_config(
    path: Path | None = None,
    root: Path | None = None,
    *,
    options: Options | None = None,
    check: bool = False,
) -> Config:
    """
    Given a file path, walk upwards looking for and applying cascading configs.
    With ``check``, the rules that the configs name are loaded, and the first one
    that cannot be raises a :class:`ConfigError` (see :func:`check_rules`).
    """
    path = (path or Path.cwd()).resolve()

    if root is not None:
        root = root.resolve()

    if options and options.config_file:
        config_paths = [options.config_file]
    else:
        config_paths = locate_configs(path, root=root)

    raw_configs = read_configs(config_paths)
    config_file = bool(options and options.config_file)
    config = merge_configs(path, raw_configs, root=root, config_file=config_file)

    if options:
        config.custom_rules = options.custom_rules

        if options.rules:
            config.enable = list(options.rules)
            config.disable = []

        if options.output_format:
            config.output_format = options.output_format

        if options.output_template:
            config.output_template = options.output_template

    if check:
        check_rules(raw_configs, config, options)

    return config


def check_configs(paths: Sequence[Path], options: Options | None = None) -> None:
    """
    Read the config of the directory of each file in ``paths``, in their order
    and once for each directory, and load the rules that it names, before any
    file is linted: the first error is raised as a :class:`ConfigError` (#40).
    With ``--config-file``, that config is read once.
    """
    if options and options.config_file:
        paths = paths[:1]
    seen: set[Path] = set()
    for path in paths:
        directory = path.resolve().parent
        if directory not in seen:
            seen.add(directory)
            generate_config(directory, options=options, check=True)


def validate_config(path: Path, *, custom_rules: bool = True) -> list[str]:
    """
    Validate the config at ``path``, alone and as a root config (#100): its
    values, as :func:`read_configs` checks them, and then every rule that it
    names, loaded as ``lint`` loads them (:func:`load_error`), with its
    ``enable-root-import``. The first value that tukuroi cannot use is the only
    error returned (#40); otherwise, each rule that cannot be loaded adds one.
    An error is as the CLI shows a :class:`ConfigError`: the file, the key, and
    the message. A file without ``[tool.tukuroi]`` has nothing to check.

    With ``custom_rules`` false, only the names of custom rules are checked: they
    are not imported, and each one logs a warning.
    """
    try:
        raw_configs = read_configs([path])
        if not raw_configs:
            return []
        config = merge_configs(path.parent, raw_configs)
    except ConfigError as error:
        return [error.describe()]
    config.custom_rules = custom_rules

    raw = raw_configs[0]
    errors: list[str] = []
    for key, names in named_rules(raw.data):
        for name in names:
            rule = parse_rule(name, raw.path.parent, raw)
            if not (custom_rules or rule.builtin):
                log_skipped(rule)
            elif error := load_error(rule, config):
                errors.append(ConfigError(f"{key}: {error}", raw).describe())
    return errors
