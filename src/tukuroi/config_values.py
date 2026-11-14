# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The values of a config that tukuroi cannot use (#40): each check gives the
messages, starting with the key, and raises nothing. :mod:`tukuroi.config`
makes them a :class:`~tukuroi.config.ConfigError` (#157).
"""

import json
from collections.abc import Iterator, Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from .ftypes import QualifiedRuleRegex
from .plugins import (
    FORMATTERS,
    NO_FORMATTER,
    OUTPUT_FORMATS,
    PluginError,
    formatter_names,
    is_builtin,
    load_formatter,
    output_format_names,
    registered,
)
from .template import template_error


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
    The messages for ``value`` of ``formatter``: none, or the name of a
    formatter plugin (#169). A plugin of tukuroi itself is loaded here, as
    ``ruff``, which needs its optional package (#108); one of another
    distribution, only where custom rules may run
    (:func:`~tukuroi.config.plugin_errors`).
    """
    if not isinstance(value, str):
        yield must_be("formatter", "a string", value)
    elif value != NO_FORMATTER:
        point = registered(FORMATTERS).get(value)
        if point is None:
            choices = ", ".join(map(repr, formatter_names()))
            yield f"formatter: unknown value {value!r}, not one of {choices}"
        elif is_builtin(point):
            try:
                load_formatter(value)
            except PluginError as error:
                yield f"formatter: {error}"


def output_format_errors(value: object) -> Iterator[str]:
    """
    The messages for ``value`` of ``output-format``: the name of an output format
    plugin (#169), in any case, as the option (#40). An empty string is unset.
    """
    if not isinstance(value, str):
        yield must_be("output-format", "a string", value)
    elif value and value.lower() not in registered(OUTPUT_FORMATS):
        choices = ", ".join(map(repr, output_format_names()))
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
