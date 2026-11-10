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

from .core.loader import CollectionError, RuleName, import_rules
from .core.loader import collect_rules as collect_core_rules
from .core.loader import load as load_core_rules
from .core.rule import Rule
from .ftypes import (
    Config,
    Options,
    OutputFormat,
    QualifiedRule,
    QualifiedRuleRegex,
    RawConfig,
)

FIXIT_CONFIG_FILENAMES = ("fixit.toml", ".fixit.toml", "pyproject.toml")


log = logging.getLogger(__name__)


class ConfigError(ValueError):
    """
    A config that fixit cannot use. ``path`` is the file, when the error is in
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
    ``fixit.rules``, and the custom rules. A rule that cannot be loaded is a
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
    The rules that ``data``, the table ``[tool.fixit]`` of a config, names, in
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
        candidates = (path / filename for filename in FIXIT_CONFIG_FILENAMES)
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

    Skips any path with no — or empty — `tool.fixit` section.
    Stops early at any config with `root = true`.

    Maintains the same order as given in paths, minus any skipped files.
    A file that is not TOML is a :class:`ConfigError`, with the message of
    :mod:`tomllib`, as is the first value of a config that fixit cannot use
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
        fixit_data = table(data, "tool", path).get("fixit", {})
        if not isinstance(fixit_data, dict):
            raise ConfigError(must_be("tool.fixit", "a table", fixit_data), path=path)

        if fixit_data:
            config = RawConfig(path=path, data=fixit_data)
            if (error := next(value_errors(config.data), None)) is not None:
                raise ConfigError(error, config=config)
            configs.append(config)

            if config.data.get("root", False):
                break

    return configs


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
    return f"a {type(value).__name__}"


def must_be(key: str, expected: str, value: object) -> str:
    """The message for ``value`` of ``key``, which is not ``expected``."""
    return f"{key}: must be {expected}, got {toml_type(value)}"


RULES = "an array of strings"
OVERRIDES = "an array of tables ([[tool.fixit.overrides]])"
# In any case, as the option (#40).
OUTPUT_FORMATS = {o.value: o for o in OutputFormat}


def value_errors(data: dict[str, Any]) -> Iterator[str]:
    """
    The messages for the values in ``data``, the table ``[tool.fixit]`` of a
    config, that fixit cannot use: a value of the wrong type, or a rule name that
    is not valid (#40). The keys are checked in their order in the file, and
    each message starts with the key.

    All the overrides are checked, whether or not they apply to the file that is
    linted. Whether a rule can be imported is not checked, and neither are the
    unknown keys, nor ``enable-root-import`` in a config that is not the root.
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
            case "output-format":
                yield from output_format_errors(value)
            case "output-template":
                if not isinstance(value, str):
                    yield must_be(key, "a string", value)
            case "overrides":
                yield from override_errors(value)


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
    path: Path, raw_configs: list[RawConfig], root: Path | None = None
) -> Config:
    """
    Given multiple raw configs, merge them in priority order.

    Assumes raw_configs are given in order from highest to lowest priority.
    """

    config: RawConfig
    enable_root_import: bool | Path = Config.enable_root_import
    enable_rules: set[QualifiedRule] = {QualifiedRule("fixit.rules")}
    disable_rules: set[QualifiedRule] = set()
    output_format: OutputFormat = OutputFormat.fixit
    output_template: str = ""

    def process_subpath(
        subpath: Path,
        *,
        enable: Sequence[str] = (),
        disable: Sequence[str] = (),
    ) -> None:
        subpath = subpath.resolve()
        try:
            path.relative_to(subpath)
        except ValueError:  # not relative to subpath
            return

        config_dir = config.path.parent
        for rule in enable:
            qual_rule = parse_rule(rule, config_dir, config)
            enable_rules.add(qual_rule)
            disable_rules.discard(qual_rule)

        for rule in disable:
            qual_rule = parse_rule(rule, config_dir, config)
            enable_rules.discard(qual_rule)
            disable_rules.add(qual_rule)

    for config in reversed(raw_configs):
        if root is None:
            root = config.path.parent

        # A copy: the configs are left as they were read, for check_rules.
        data = dict(config.data)
        if data.pop("root", False):
            root = config.path.parent

        # The values are checked as the config is read (read_configs), but where
        # the root is depends on the configs that are merged.
        if value := data.pop("enable-root-import", False):
            if root != config.path.parent:
                raise ConfigError(
                    "enable-root-import: only allowed in a root config", config=config
                )
            enable_root_import = Path(value) if isinstance(value, str) else True

        if value := data.pop("output-format", ""):
            output_format = OUTPUT_FORMATS[value.lower()]

        if value := data.pop("output-template", ""):
            output_template = value

        process_subpath(
            config.path.parent,
            enable=data.pop("enable", ()),
            disable=data.pop("disable", ()),
        )

        for override in data.pop("overrides", ()):
            process_subpath(
                config.path.parent / override["path"],
                enable=override.get("enable", ()),
                disable=override.get("disable", ()),
            )

        for key in data:
            log.warning("unknown configuration option %r", key)

    return Config(
        path=path,
        root=root or Path(path.anchor),
        enable_root_import=enable_root_import,
        enable=sorted(enable_rules),
        disable=sorted(disable_rules),
        output_format=output_format,
        output_template=output_template,
    )


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
    config = merge_configs(path, raw_configs, root=root)

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
    Validate the config provided. The provided path is expected to be a valid toml
    config file. The first value that fixit cannot use, as :func:`read_configs`
    finds it, is the only exception returned (#40). Otherwise, each rule that
    cannot be imported adds one to the list of exceptions that are returned.

    With ``custom_rules`` false, only the names of custom rules are checked: they
    are not imported, and each one logs a warning.
    """
    exceptions: list[str] = []
    try:
        root = path.parent
        configs = read_configs([path])[0]

        def validate_rules(rules: list[str], context: str) -> None:
            for rule in rules:
                # read_configs checked the name.
                qualified_rule = parse_rule(rule, root, configs)
                if not (custom_rules or qualified_rule.builtin):
                    log_skipped(qualified_rule)
                    continue
                try:
                    import_rules(rule_name(qualified_rule))
                # Importing a rule runs its code, which can raise any exception.
                except Exception as e:  # noqa: BLE001
                    exceptions.append(
                        f"Failed to import rule `{rule}` for {context}: {e.__class__.__name__}: {e}"
                    )

        data = configs.data
        validate_rules(data.get("enable", []), "global enable")
        validate_rules(data.get("disable", []), "global disable")

        for override in data.get("overrides", []):
            override_path = Path(override["path"])
            validate_rules(
                override.get("enable", []),
                f"override enable: `{override_path}`",
            )
            validate_rules(
                override.get("disable", []),
                f"override disable: `{override_path}`",
            )

    # Report any error as a validation result instead of failing.
    except Exception as e:  # noqa: BLE001
        exceptions.append(f"Invalid config: {e.__class__.__name__}: {e}")

    return exceptions
