# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.plugins`` (#169): the formatter plugins, registered in the
entry points of ``tukuroi.formatters``. The plugins of other distributions are
entry points made here, in place of those of the environment.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from .. import plugins
from ..core.format import FormatterPlugin, RuffFormatter


class Upper:
    """A formatter that writes the text in upper case."""

    def available(self) -> str | None:
        return None

    def format(self, text: str, path: Path | None) -> str:
        return text.upper()


class Missing(Upper):
    """A formatter that cannot run."""

    def available(self) -> str | None:
        return "needs the upper package"


class NotAFormatter:
    """No format()."""


def raises() -> type:
    raise ImportError("no module named 'upper'")


@dataclass(frozen=True)
class Distribution:
    name: str


@dataclass(frozen=True)
class Point:
    """An entry point: its name, the distribution, and what it loads."""

    name: str
    value: str
    dist: Distribution | None
    loaded: Callable[[], type]

    def load(self) -> type:
        return self.loaded()


THEIRS = Distribution("tukuroi-upper")
OURS = Distribution("tukuroi")


@contextmanager
def points(*found: Point) -> Iterator[None]:
    """The entry points of ``tukuroi.formatters`` are ``found``."""
    plugins.registered.cache_clear()
    try:
        with patch.object(plugins, "entry_points", return_value=list(found)):
            yield
    finally:
        plugins.registered.cache_clear()


def point(
    name: str, loaded: Callable[[], type], dist: Distribution | None = THEIRS
) -> Point:
    return Point(name, f"tukuroi_{name}:Plugin", dist, loaded)


class PluginsTest(TestCase):
    def test_ruff_is_built_in(self) -> None:
        self.assertEqual(plugins.formatter_names(), ["none", "ruff"])
        self.assertTrue(
            plugins.is_builtin(plugins.registered(plugins.FORMATTERS)["ruff"])
        )
        loaded = plugins.load_formatter("ruff")
        self.assertIsInstance(loaded, RuffFormatter)
        self.assertIsInstance(loaded, FormatterPlugin)

    def test_load_formatter(self) -> None:
        with points(point("upper", lambda: Upper)):
            self.assertEqual(plugins.formatter_names(), ["none", "upper"])
            self.assertEqual(plugins.load_formatter("upper").format("x", None), "X")

    def test_formatters_that_cannot_be_used(self) -> None:
        cases = (
            # (label, the entry point, the message)
            ("unknown", None, "unknown value 'upper', not one of 'none'"),
            ("not loaded", point("upper", raises), "could not load 'upper': ImportError: no module named 'upper'"),
            ("not a formatter", point("upper", lambda: NotAFormatter), "'upper' is not a formatter: tukuroi_upper:Plugin"),
            ("not available", point("upper", lambda: Missing), '"upper" needs the upper package'),
        )  # fmt: skip
        for label, found, message in cases:
            with self.subTest(label), points(*([found] if found else [])):
                with self.assertRaises(plugins.PluginError) as caught:
                    plugins.load_formatter("upper")
                self.assertEqual(str(caught.exception), message)

    def test_formatter_of(self) -> None:
        # Without custom rules, only the plugins of tukuroi itself (#12).
        with points(point("upper", lambda: Upper), point("ours", lambda: Upper, OURS)):
            cases = (
                # (name, custom, a formatter)
                ("none", True, False),
                ("upper", True, True),
                ("upper", False, False),
                ("ours", False, True),
            )
            for name, custom, found in cases:
                with self.subTest(name, custom=custom):
                    formatter = plugins.formatter_of(name, custom=custom)
                    self.assertEqual(formatter is not None, found)

    def test_a_name_registered_twice(self) -> None:
        # The plugin of tukuroi wins, in either order; else the first.
        for found in (
            [point("upper", lambda: Missing), point("upper", lambda: Upper, OURS)],
            [point("upper", lambda: Upper, OURS), point("upper", lambda: Missing)],
        ):
            with (
                self.subTest(order=[p.dist.name for p in found if p.dist]),
                points(*found),
            ):
                self.assertTrue(
                    plugins.is_builtin(plugins.registered(plugins.FORMATTERS)["upper"])
                )
        with points(
            point("upper", lambda: Upper), point("upper", lambda: Missing, None)
        ):
            self.assertEqual(plugins.load_formatter("upper").format("x", None), "X")
