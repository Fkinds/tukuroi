# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The plugins of tukuroi (#169): the classes that distributions register in the
entry points of a group, by name. tukuroi registers its own the same way. With
custom rules turned off (#12), only those of tukuroi itself are used.
"""

from functools import cache
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from .core import loader
from .core.format import FormatterPlugin
from .ftypes import Config
from .output import OutputFormatPlugin

FORMATTERS = "tukuroi.formatters"
OUTPUT_FORMATS = "tukuroi.output_formats"
# The name of no formatter: the fixes are not formatted (#108).
NO_FORMATTER = "none"
# The output format of a config that names none, and in place of one of
# another distribution with custom rules turned off.
DEFAULT_OUTPUT_FORMAT = "tukuroi"
# The distribution of tukuroi, whose plugins are built in.
DISTRIBUTION = "tukuroi"


class PluginError(Exception):
    """A plugin that cannot be used: the message says why."""


@cache
def registered(group: str) -> dict[str, EntryPoint]:
    """
    The entry points of ``group``, by name, read once in a process. When two
    distributions register a name, that of tukuroi wins, or else the first.
    The names of output formats are in lower case: they are taken in any case,
    as before (#40).
    """
    found: dict[str, EntryPoint] = {}
    for point in entry_points(group=group):
        name = point.name.lower() if group == OUTPUT_FORMATS else point.name
        if name not in found or is_builtin(point):
            found[name] = point
    return found


def is_builtin(point: EntryPoint) -> bool:
    """Whether tukuroi itself registers ``point``."""
    return point.dist is not None and point.dist.name == DISTRIBUTION


def formatter_names() -> list[str]:
    """The names that ``formatter`` takes: none, and those registered."""
    return [NO_FORMATTER, *sorted(registered(FORMATTERS))]


def output_format_names() -> list[str]:
    """The names that ``output-format`` takes: those registered."""
    return sorted(registered(OUTPUT_FORMATS))


def _load(group: str, name: str, names: list[str], *arguments: Any) -> Any:
    """
    The plugin of ``group`` registered as ``name``, made with ``arguments``.
    Raises :class:`PluginError` when no plugin has the name (one of
    ``names``), or when it cannot be loaded or made.
    """
    point = registered(group).get(name)
    if point is None:
        choices = ", ".join(map(repr, names))
        raise PluginError(f"unknown value {name!r}, not one of {choices}")
    try:
        return point.load()(*arguments)
    except Exception as error:
        message = f"could not load {name!r}: {type(error).__name__}: {error}"
        raise PluginError(message) from error


def _value(group: str, name: str) -> str:
    return registered(group)[name].value


def load_formatter(name: str) -> FormatterPlugin:
    """
    The formatter registered as ``name``, made and ready to run. Raises
    :class:`PluginError` when it cannot be loaded or made, when it is not a
    formatter, or when it says that it cannot run.
    """
    plugin = _load(FORMATTERS, name, formatter_names())
    if not isinstance(plugin, FormatterPlugin):
        raise PluginError(f"{name!r} is not a formatter: {_value(FORMATTERS, name)}")
    if reason := plugin.available():
        raise PluginError(f'"{name}" {reason}')
    return plugin


def load_output_format(name: str, config: Config) -> OutputFormatPlugin:
    """
    The output format registered as ``name``, made for ``config``. Raises
    :class:`PluginError` as :func:`load_formatter` does.
    """
    plugin = _load(OUTPUT_FORMATS, name, output_format_names(), config)
    if not isinstance(plugin, OutputFormatPlugin):
        value = _value(OUTPUT_FORMATS, name)
        raise PluginError(f"{name!r} is not an output format: {value}")
    return plugin


def formatter_of(name: str, *, custom: bool) -> FormatterPlugin | None:
    """
    The formatter of ``formatter = name``: ``None`` for none, and for one that
    tukuroi does not build in, with custom rules turned off (``custom``).
    """
    if name == NO_FORMATTER:
        return None
    point = registered(FORMATTERS).get(name)
    if point is not None and not custom and not is_builtin(point):
        return None
    return load_formatter(name)


def output_format_of(config: Config) -> OutputFormatPlugin:
    """
    The output format of ``config``. With custom rules turned off, one of
    another distribution is not loaded: the default, with a warning.
    """
    name = config.output_format
    point = registered(OUTPUT_FORMATS).get(name)
    if point is not None and not config.custom_rules and not is_builtin(point):
        message = f"Skipped output format {name!r}: custom rules are turned off"
        loader.WARNINGS.warn(message)
        name = DEFAULT_OUTPUT_FORMAT
    return load_output_format(name, config)
