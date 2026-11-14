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

from .core.format import FormatterPlugin

FORMATTERS = "tukuroi.formatters"
# The name of no formatter: the fixes are not formatted (#108).
NO_FORMATTER = "none"
# The distribution of tukuroi, whose plugins are built in.
DISTRIBUTION = "tukuroi"


class PluginError(Exception):
    """A plugin that cannot be used: the message says why."""


@cache
def registered(group: str) -> dict[str, EntryPoint]:
    """
    The entry points of ``group``, by name, read once in a process. When two
    distributions register a name, that of tukuroi wins, or else the first.
    """
    found: dict[str, EntryPoint] = {}
    for point in entry_points(group=group):
        if point.name not in found or is_builtin(point):
            found[point.name] = point
    return found


def is_builtin(point: EntryPoint) -> bool:
    """Whether tukuroi itself registers ``point``."""
    return point.dist is not None and point.dist.name == DISTRIBUTION


def formatter_names() -> list[str]:
    """The names that ``formatter`` takes: none, and those registered."""
    return [NO_FORMATTER, *sorted(registered(FORMATTERS))]


def load_formatter(name: str) -> FormatterPlugin:
    """
    The formatter registered as ``name``, made and ready to run. Raises
    :class:`PluginError` when it cannot be loaded or made, when it is not a
    formatter, or when it says that it cannot run.
    """
    point = registered(FORMATTERS).get(name)
    if point is None:
        choices = ", ".join(map(repr, formatter_names()))
        raise PluginError(f"unknown value {name!r}, not one of {choices}")
    try:
        plugin = point.load()()
    except Exception as error:
        message = f"could not load {name!r}: {type(error).__name__}: {error}"
        raise PluginError(message) from error
    if not isinstance(plugin, FormatterPlugin):
        raise PluginError(f"{name!r} is not a formatter: {point.value}")
    if reason := plugin.available():
        raise PluginError(f'"{name}" {reason}')
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
