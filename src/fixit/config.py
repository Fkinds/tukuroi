# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging
import platform
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import (
    Any,
)

from packaging.version import InvalidVersion, Version

from .core.loader import RuleName, import_rules
from .core.loader import collect_rules as collect_core_rules
from .core.rule import Rule
from .format import FORMAT_STYLES
from .ftypes import (
    Config,
    Options,
    OutputFormat,
    QualifiedRule,
    QualifiedRuleRegex,
    RawConfig,
    RuleOptionsTable,
    RuleOptionTypes,
    is_sequence,
)

FIXIT_CONFIG_FILENAMES = ("fixit.toml", ".fixit.toml", "pyproject.toml")


log = logging.getLogger(__name__)


class ConfigError(ValueError):
    def __init__(self, msg: str, config: RawConfig | None = None):
        super().__init__(msg)
        self.config = config


def log_skipped(rule: QualifiedRule) -> None:
    """Warn that ``rule``, a custom rule, is not imported."""
    log.warning(f"Skipped rules '{rule}': custom rules are turned off")


def load_rules(config: Config) -> tuple[type[Rule], ...]:
    """
    The rules that ``config`` enables, sorted by name: the built-in rules in
    ``fixit.rules``, and the custom rules. ``tags`` and ``python-version`` do not
    apply to them. A module that cannot be imported is a warning.
    """
    root_import = None
    if config.enable_root_import:
        root_import = config.root
        if isinstance(config.enable_root_import, Path):
            root_import = config.root / config.enable_root_import
    return collect_core_rules(
        [rule_name(rule) for rule in config.enable],
        [rule_name(rule) for rule in config.disable],
        root_import=root_import,
        custom_rules=config.custom_rules,
    )


def rule_name(rule: QualifiedRule) -> RuleName:
    """
    ``rule`` as the new engine names it: with the directory, made absolute, only
    for a local rule. ``validate-config`` gives the directory of its path as is.
    """
    root = rule.root.resolve() if rule.local and rule.root else None
    return RuleName(rule.module, rule.name, root)


def locate_configs(path: Path, root: Path | None = None) -> list[Path]:
    """
    Given a file path, locate all relevant config files in priority order.

    Walking upward from target path, creates a list of candidate paths that exist
    on disk, ordered from nearest/highest priority to further/lowest priority.

    If root is given, only return configs between path and root (inclusive), ignoring
    any paths outside of root, even if they would contain relevant configs.
    If given, root must contain path.

    Returns a list of config paths in priority order, from highest priority to lowest.
    """
    results: list[Path] = []

    if not path.is_dir():
        path = path.parent

    root = root.resolve() if root is not None else Path(path.anchor)
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
    """
    configs: list[RawConfig] = []

    for path in paths:
        path = path.resolve()
        content = path.read_text()
        data = tomllib.loads(content)
        fixit_data = data.get("tool", {}).get("fixit", {})

        if fixit_data:
            config = RawConfig(path=path, data=fixit_data)
            configs.append(config)

            if config.data.get("root", False):
                break

    return configs


def get_sequence(
    config: RawConfig, key: str, *, data: dict[str, Any] | None = None
) -> Sequence[str]:
    value: Sequence[str]
    if data:
        value = data.pop(key, ())
    else:
        value = config.data.pop(key, ())

    if not is_sequence(value):
        raise ConfigError(
            f"{key!r} must be array of values, got {type(key)}", config=config
        )

    return value


def get_options(
    config: RawConfig, key: str, *, data: dict[str, Any] | None = None
) -> RuleOptionsTable:
    if data:
        mapping = data.pop(key, {})
    else:
        mapping = config.data.pop(key, {})

    if not isinstance(mapping, Mapping):
        raise ConfigError(
            f"{key!r} must be mapping of values, got {type(key)}", config=config
        )

    rule_configs: RuleOptionsTable = {}
    for rule_name, rule_config in mapping.items():
        rule_configs[rule_name] = {}
        for option, value in rule_config.items():
            if not isinstance(value, RuleOptionTypes):
                raise ConfigError(
                    f"{option!r} must be one of {RuleOptionTypes}, got {type(value)}",
                    config=config,
                )

            rule_configs[rule_name][option] = value

    return rule_configs


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
    rule_options: RuleOptionsTable = {}
    target_python_version: Version | None = Version(platform.python_version())
    target_formatter: str | None = None
    output_format: OutputFormat = OutputFormat.fixit
    output_template: str = ""

    def process_subpath(
        subpath: Path,
        *,
        enable: Sequence[str] = (),
        disable: Sequence[str] = (),
        options: RuleOptionsTable | None = None,
        python_version: Any = None,
        formatter: str | None = None,
    ) -> None:
        nonlocal target_python_version
        nonlocal target_formatter

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

        if options:
            rule_options.update(options)

        if python_version is not None:
            if python_version:
                try:
                    target_python_version = Version(python_version)
                except InvalidVersion:
                    raise ConfigError(
                        f"'python-version' {python_version!r} is not valid",
                        config=config,
                    )

            else:  # disable versioning, aka python-version = ""
                target_python_version = None

        if formatter:
            if formatter not in FORMAT_STYLES:
                raise ConfigError(
                    f"'formatter' {formatter!r} not supported", config=config
                )

            target_formatter = formatter

    for config in reversed(raw_configs):
        if root is None:
            root = config.path.parent

        data = config.data
        if data.pop("root", False):
            root = config.path.parent

        value = data.pop("enable-root-import", False)
        # A bool, or a relative path that is not empty (#21).
        if not isinstance(value, (bool, str)) or value == "":
            raise ConfigError(
                f"enable-root-import: {value!r} is not a bool or a relative path",
                config=config,
            )
        if value:
            if root != config.path.parent:
                raise ConfigError(
                    "enable-root-import not allowed in non-root configs", config=config
                )
            if isinstance(value, str):
                value_path = Path(value)
                if value_path.is_absolute():
                    raise ConfigError(
                        "enable-root-import: absolute paths not allowed", config=config
                    )
                if ".." in value_path.parts:
                    raise ConfigError(
                        "enable-root-import: '..' components not allowed", config=config
                    )
                enable_root_import = value_path
            else:
                enable_root_import = True

        if value := data.pop("output-format", ""):
            try:
                output_format = OutputFormat(value)
            except ValueError as e:
                raise ConfigError(
                    "output-format: unknown value {value!r}", config=config
                ) from e

        if value := data.pop("output-template", ""):
            output_template = value

        process_subpath(
            config.path.parent,
            enable=get_sequence(config, "enable"),
            disable=get_sequence(config, "disable"),
            options=get_options(config, "options"),
            python_version=config.data.pop("python-version", None),
            formatter=config.data.pop("formatter", None),
        )

        for override in get_sequence(config, "overrides"):
            if not isinstance(override, dict):
                raise ConfigError("'overrides' requires array of tables", config=config)

            subpath = override.get("path", None)
            if not subpath:
                raise ConfigError(
                    "'overrides' table requires 'path' value", config=config
                )

            subpath = config.path.parent / subpath
            process_subpath(
                subpath,
                enable=get_sequence(config, "enable", data=override),
                disable=get_sequence(config, "disable", data=override),
                options=get_options(config, "options", data=override),
                python_version=override.pop("python-version", None),
                formatter=override.pop("formatter", None),
            )

        for key in data:
            log.warning("unknown configuration option %r", key)

    return Config(
        path=path,
        root=root or Path(path.anchor),
        enable_root_import=enable_root_import,
        enable=sorted(enable_rules),
        disable=sorted(disable_rules),
        options=rule_options,
        python_version=target_python_version,
        formatter=target_formatter,
        output_format=output_format,
        output_template=output_template,
    )


def generate_config(
    path: Path | None = None,
    root: Path | None = None,
    *,
    options: Options | None = None,
) -> Config:
    """
    Given a file path, walk upwards looking for and applying cascading configs
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

        if options.tags:
            config.tags = options.tags

        if options.rules:
            config.enable = list(options.rules)
            config.disable = []

        if options.output_format:
            config.output_format = options.output_format

        if options.output_template:
            config.output_template = options.output_template

    return config


def validate_config(path: Path, *, custom_rules: bool = True) -> list[str]:
    """
    Validate the config provided. The provided path is expected to be a valid toml
    config file. Any exception found while parsing or importing will be added to a list
    of exceptions that are returned.

    With ``custom_rules`` false, only the names of custom rules are checked: they
    are not imported, and each one logs a warning.
    """
    exceptions: list[str] = []
    try:
        root = path.parent
        configs = read_configs([path])[0]

        def validate_rules(rules: list[str], context: str) -> None:
            for rule in rules:
                try:
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
                # Report any error as a validation result instead of failing.
                except Exception as e:  # noqa: BLE001
                    exceptions.append(
                        f"Failed to parse rule `{rule}` for {context}: {e.__class__.__name__}: {e}"
                    )

        data = configs.data
        validate_rules(data.get("enable", []), "global enable")
        validate_rules(data.get("disable", []), "global disable")

        for override in data.get("overrides", []):
            override_path = Path(override.get("path", path))
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
