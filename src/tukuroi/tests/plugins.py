# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.plugins`` (#169): the formatter plugins and the output format
plugins, registered in the entry points of ``tukuroi.formatters`` and
``tukuroi.output_formats``. The plugins of other distributions are entry points
made here, in place of those of the environment.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from unittest import TestCase
from unittest.mock import call, patch

from .. import plugins
from ..core import loader
from ..core.format import FormatterPlugin, RuffFormatter
from ..core.text import Position, Range
from ..documents import JsonFormat, SarifFormat
from ..ftypes import Config, Result, Violation
from ..output import (
    CustomFormat,
    OutputFormatPlugin,
    TukuroiFormat,
    VscodeFormat,
    machine_readable,
)
from .characterization_cli import (
    CONFIG,
    DIRTY_A,
    DIRTY_F,
    FIXABLE,
    FIXED,
    NA,
    invoke,
    line,
)
from .core_loader import new_process


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


class Shout:
    """An output format: a line in upper case for each violation, in a frame."""

    def __init__(self, config: Config) -> None:
        self.config = config

    def start(self) -> str | None:
        return "START"

    def result(self, result: Result) -> str | None:
        if result.violation is None:
            return None
        return f"{result.path.name}: {result.violation.rule_name}".upper()

    def end(self) -> str | None:
        return "END"


class NotAnOutputFormat:
    """Made with a config, but no start(), result() or end()."""

    def __init__(self, config: Config) -> None:
        self.config = config


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
def points(
    *found: Point, group: str = plugins.FORMATTERS, builtin: bool = False
) -> Iterator[None]:
    """
    The entry points of ``group`` are ``found``, after those of tukuroi itself
    with ``builtin``; those of the other groups are those of the environment.
    """

    def found_in(*, group: str) -> list[EntryPoint | Point]:
        real: list[EntryPoint | Point] = list(entry_points(group=group))
        return [*(real if builtin else []), *found] if group == wanted else real

    wanted = group
    plugins.registered.cache_clear()
    try:
        with patch.object(plugins, "entry_points", side_effect=found_in):
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


OUTPUT = plugins.OUTPUT_FORMATS
VIOLATION = Result(
    Path("t.py"), Violation("NoBad", Range(Position(1, 0), Position(1, 1)), "m", False)
)


class OutputFormatPluginsTest(TestCase):
    def test_built_in(self) -> None:
        names = ["custom", "json", "sarif", "tukuroi", "vscode"]
        self.assertEqual(plugins.output_format_names(), names)
        for name, made, machine in (
            ("custom", CustomFormat, False),
            ("tukuroi", TukuroiFormat, False),
            # One document at the end (#178).
            ("json", JsonFormat, True),
            ("sarif", SarifFormat, True),
            ("vscode", VscodeFormat, False),
        ):
            with self.subTest(name):
                point = plugins.registered(OUTPUT)[name]
                self.assertTrue(plugins.is_builtin(point))
                loaded = plugins.load_output_format(name, Config())
                self.assertIs(type(loaded), made)
                self.assertIsInstance(loaded, OutputFormatPlugin)
                self.assertIs(machine_readable(loaded), machine)
                self.assertIsNone(loaded.start())
                end = loaded.end()
                if machine:
                    assert end is not None
                    json.loads(end)
                else:
                    self.assertIsNone(end)

    def test_load_output_format(self) -> None:
        # Made with the config of the run; the names are in any case (#40).
        config = Config(output_template="x")
        for name in ("shout", "Shout"):
            with (
                self.subTest(name),
                points(point(name, lambda: Shout), group=OUTPUT),
            ):
                self.assertEqual(plugins.output_format_names(), ["shout"])
                loaded = plugins.load_output_format("shout", config)
                assert isinstance(loaded, Shout)
                self.assertIs(loaded.config, config)
                self.assertEqual(loaded.result(VIOLATION), "T.PY: NOBAD")

    def test_output_formats_that_cannot_be_used(self) -> None:
        cases = (
            # (label, the entry point, the message)
            ("unknown", None, "unknown value 'shout', not one of 'custom', 'json', 'sarif', 'tukuroi', 'vscode'"),
            ("not loaded", point("shout", raises), "could not load 'shout': ImportError: no module named 'upper'"),
            ("not an output format", point("shout", lambda: NotAnOutputFormat), "'shout' is not an output format: tukuroi_shout:Plugin"),
        )  # fmt: skip
        for label, found, message in cases:
            with (
                self.subTest(label),
                points(*([found] if found else []), group=OUTPUT, builtin=True),
            ):
                with self.assertRaises(plugins.PluginError) as caught:
                    plugins.load_output_format("shout", Config())
                self.assertEqual(str(caught.exception), message)

    def test_output_format_of(self) -> None:
        # Without custom rules, only the plugins of tukuroi itself (#12): the
        # default, with a warning, in place of another.
        warning = "Skipped output format 'shout': custom rules are turned off"
        found = (point("shout", lambda: Shout), point("ours", lambda: Shout, OURS))
        cases = (
            # (name, custom, the format, the warnings)
            ("shout", True, Shout, []),
            ("shout", False, TukuroiFormat, [call(warning)]),
            ("ours", False, Shout, []),
            ("vscode", False, VscodeFormat, []),
        )
        for name, custom, made, warnings in cases:
            with (
                self.subTest(name, custom=custom),
                points(*found, group=OUTPUT, builtin=True),
                new_process(),
                patch.object(loader.log, "warning") as warn,
            ):
                config = Config(output_format=name, custom_rules=custom)
                self.assertIs(type(plugins.output_format_of(config)), made)
                self.assertEqual(warn.call_args_list, warnings)

    def test_cli(self) -> None:
        # A format of another distribution, named by the option or the config:
        # what it gives at the start and the end, around the results.
        found = point("shout", lambda: Shout)
        by_option = {"pyproject.toml": CONFIG, "t.py": FIXABLE}
        by_config = {
            **by_option,
            "pyproject.toml": CONFIG + 'output-format = "Shout"\n',
        }
        shout = f"START\nT.PY: {NA.upper()}\nEND\n"
        skipped = "WARNING:tukuroi.config:Skipped output format 'shout': custom rules are turned off\n"
        cases = (
            # (label, files, args, stdout, stderr)
            ("option", by_option, ["-o", "SHOUT", "lint", "t.py"], shout, DIRTY_A),
            ("config", by_config, ["lint", "t.py"], shout, DIRTY_A),
            ("fix", by_option, ["-o", "shout", "fix", "-a", "t.py"], shout, DIRTY_F),
            # Without custom rules (#12): the default, with a warning.
            ("no custom rules, option", by_option, ["--no-custom-rules", "-o", "shout", "lint", "t.py"], line("t.py", NA), skipped + DIRTY_A),
            ("no custom rules, config", by_config, ["--no-custom-rules", "lint", "t.py"], line("t.py", NA), skipped + DIRTY_A),
        )  # fmt: skip
        for label, files, args, stdout, stderr in cases:
            with self.subTest(label), points(found, group=OUTPUT, builtin=True):
                result = invoke(files, args)
                self.assertEqual(result.stdout, stdout)
                self.assertEqual(result.stderr, stderr)
        with self.subTest("fix stdin"), points(found, group=OUTPUT, builtin=True):
            # The fixed source alone on stdout, as before (#40).
            args = ["-o", "shout", "fix", "-", "t.py"]
            result = invoke({"pyproject.toml": CONFIG}, args, stdin=FIXABLE)
            self.assertEqual(result.stdout, FIXED)
            self.assertEqual(result.stderr, shout + DIRTY_F)

    def test_cli_cannot_be_used(self) -> None:
        # A config that tukuroi cannot use, before any file is linted.
        files = {
            "pyproject.toml": CONFIG + 'output-format = "shout"\n',
            "t.py": FIXABLE,
        }
        loaded = "could not load 'shout': ImportError: no module named 'upper'"
        cases = (
            # (args, stderr)
            (["lint", "t.py"], f"Error: output-format: {loaded}\n"),
            (["-o", "shout", "lint", "t.py"], f"Error: output-format: {loaded}\n"),
            (["validate-config", "pyproject.toml"], f"Error: pyproject.toml: output-format: {loaded}\n"),
        )  # fmt: skip
        for args, stderr in cases:
            with (
                self.subTest(" ".join(args)),
                points(point("shout", raises), group=OUTPUT, builtin=True),
            ):
                result = invoke(files, args)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.stderr, stderr)
                self.assertEqual(result.exit_code, 2)
