# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The output formats for programs to read (#178): the documents of ``json`` and
``sarif`` from the results, and the CLI with them, which prints nothing else
on stdout.
"""

import io
import json
from collections.abc import Generator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import TestCase
from unittest.mock import patch

from .. import documents
from ..cli import metrics_hook, print_to_stderr
from ..config import ConfigError
from ..core.rule import Rule
from ..core.text import Position, Range
from ..documents import JsonFormat, SarifFormat
from ..ftypes import Config, Error, Options, Result, Violation
from ..output import TukuroiFormat, machine_readable
from ..util import chdir
from .characterization_cli import (
    BROKEN,
    CONFIG,
    DIRTY_A,
    DIRTY_F,
    FIXABLE,
    FIXED,
    NA,
    invoke,
)

FIRST = Range(Position(1, 0), Position(1, 3))
SECOND = Range(Position(2, 4), Position(3, 0))
OUTSIDE = Path("/elsewhere/e.py")


class FirstRule(Rule):
    """
    The first rule,
    on two lines.

    And more.
    """

    MESSAGE = "a first"


class DocumentedRule(Rule):
    """
    Reports what is documented,
    on two lines.

    And more.
    """


class BareRule(Rule):
    pass


def results(root: Path) -> list[Result]:
    """The results of a run in ``root``, out of order, of each kind."""
    return [
        Result(root / "b.py", Violation("Second", SECOND, "second", False)),
        Result(root / "b.py", Violation("First", FIRST, "first", True, "DIFF")),
        Result(root / "a b ü.py", None),
        Result(root / "d.py", None, error=Error("ParseError", "x", "", Position(3, 1))),
        Result(root / "c.py", None, error=Error("ValueError", "bad", "Traceback\n")),
        Result(root / "b.py", None, applied=1, remaining=1),
        Result(OUTSIDE, Violation("First", FIRST, "first", False)),
    ]


@contextmanager
def directory() -> Generator[Path]:
    """A new directory, as the current one."""
    with TemporaryDirectory() as td:
        root = Path(td).resolve()
        with chdir(root):
            yield root


def document(kind: type[JsonFormat | SarifFormat], root: Path) -> Any:
    """The document that ``kind`` prints for the results in ``root``: at the end only."""
    output = kind(Config())
    texts = [output.start(), *(output.result(r) for r in results(root))]
    printed = [text for text in texts if text is not None]
    assert not printed, printed
    end = output.end()
    assert end is not None
    return json.loads(end)


def sarif_location(uri: str, region: dict[str, int] | None) -> dict[str, Any]:
    base = {} if uri.startswith("file:") else {"uriBaseId": "%SRCROOT%"}
    physical: dict[str, Any] = {"artifactLocation": {"uri": uri, **base}}
    if region is not None:
        physical["region"] = region
    return {"physicalLocation": physical}


class DocumentsTest(TestCase):
    maxDiff = None

    def test_json(self) -> None:
        with directory() as root:
            found = document(JsonFormat, root)
        expected = {
            "files": ["/elsewhere/e.py", "a b ü.py", "b.py", "c.py", "d.py"],
            "violations": [
                {"path": "/elsewhere/e.py", "rule": "First", "message": "first", "autofixable": False, "start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 3}, "diff": None},
                {"path": "b.py", "rule": "First", "message": "first", "autofixable": True, "start": {"line": 1, "column": 0}, "end": {"line": 1, "column": 3}, "diff": "DIFF"},
                {"path": "b.py", "rule": "Second", "message": "second", "autofixable": False, "start": {"line": 2, "column": 4}, "end": {"line": 3, "column": 0}, "diff": None},
            ],
            "errors": [
                {"path": "c.py", "type": "ValueError", "message": "bad", "traceback": "Traceback\n", "position": None},
                {"path": "d.py", "type": "ParseError", "message": "x", "traceback": None, "position": {"line": 3, "column": 1}},
            ],
            "fixed": [{"path": "b.py", "applied": 1, "remaining": 1}],
        }  # fmt: skip
        self.assertEqual(found, expected)

    def test_json_is_ascii(self) -> None:
        # Whatever the encoding of the output (RFC 8259 asks for UTF-8).
        with directory() as root:
            output = JsonFormat(Config())
            output.result(Result(root / "ü.py", None))
            end = output.end()
        assert end is not None
        self.assertTrue(end.isascii())
        self.assertEqual(json.loads(end)["files"], ["ü.py"])

    def test_sarif(self) -> None:
        enabled = (FirstRule, DocumentedRule, BareRule)
        with (
            directory() as root,
            patch.object(documents, "load_rules", return_value=enabled) as load,
        ):
            found = document(SarifFormat, root)
        self.assertIsInstance(load.call_args.args[0], Config)
        first = {
            "id": "First",
            "shortDescription": {"text": "a first"},
            "fullDescription": {"text": "The first rule,\non two lines.\n\nAnd more."},
            "help": {"text": "The first rule,\non two lines.\n\nAnd more."},
        }
        documented = "Reports what is documented,\non two lines.\n\nAnd more."
        rules = [
            # Neither a message nor a docstring: the name.
            {"id": "Bare", "shortDescription": {"text": "Bare"}, "fullDescription": {"text": "Bare"}, "help": {"text": "Bare"}},
            # No message: the first paragraph of the docstring.
            {"id": "Documented", "shortDescription": {"text": "Reports what is documented, on two lines."}, "fullDescription": {"text": documented}, "help": {"text": documented}},
            first,
            # Reported, but not enabled by the config: the name.
            {"id": "Second", "shortDescription": {"text": "Second"}, "fullDescription": {"text": "Second"}, "help": {"text": "Second"}},
        ]  # fmt: skip
        region = {"startLine": 1, "startColumn": 1, "endLine": 1, "endColumn": 4}
        results = [
            {"ruleId": "First", "ruleIndex": 2, "level": "warning", "message": {"text": "first"}, "locations": [sarif_location("file:///elsewhere/e.py", region)]},
            {"ruleId": "First", "ruleIndex": 2, "level": "warning", "message": {"text": "first"}, "locations": [sarif_location("b.py", region)]},
            # The column after the end, from 1.
            {"ruleId": "Second", "ruleIndex": 3, "level": "warning", "message": {"text": "second"}, "locations": [sarif_location("b.py", {"startLine": 2, "startColumn": 5, "endLine": 3, "endColumn": 1})]},
        ]  # fmt: skip
        notifications = [
            {"level": "error", "message": {"text": "ValueError: bad"}, "locations": [sarif_location("c.py", None)], "exception": {"kind": "ValueError", "message": "bad"}},
            {"level": "error", "message": {"text": "ParseError: x"}, "locations": [sarif_location("d.py", {"startLine": 3, "startColumn": 2})], "exception": {"kind": "ParseError", "message": "x"}},
        ]  # fmt: skip
        expected = {
            "$schema": documents.SARIF_SCHEMA,
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "tukuroi",
                            "version": documents.__version__,
                            "informationUri": "https://fkinds.github.io/tukuroi/",
                            "rules": rules,
                        }
                    },
                    "invocations": [
                        {
                            "executionSuccessful": False,
                            "toolExecutionNotifications": notifications,
                        }
                    ],
                    "originalUriBaseIds": {"%SRCROOT%": {"uri": root.as_uri() + "/"}},
                    "columnKind": "unicodeCodePoints",
                    "results": results,
                }
            ],
        }
        self.assertEqual(found, expected)

    def test_sarif_uris(self) -> None:
        # Relative URIs, percent-encoded (RFC 3986), and absolute ones outside.
        with directory() as root:
            output = SarifFormat(Config())
            for path in (root / "a b ü.py", root / "sub" / "c%.py", OUTSIDE):
                output.result(Result(path, Violation("First", FIRST, "m", False)))
            end = output.end()
        assert end is not None
        [run] = json.loads(end)["runs"]
        uris = [
            result["locations"][0]["physicalLocation"]["artifactLocation"]
            for result in run["results"]
        ]
        expected = [
            {"uri": "file:///elsewhere/e.py"},
            {"uri": "a%20b%20%C3%BC.py", "uriBaseId": "%SRCROOT%"},
            {"uri": "sub/c%25.py", "uriBaseId": "%SRCROOT%"},
        ]
        self.assertEqual(uris, expected)

    def test_sarif_successful(self) -> None:
        # No error: a successful run, and the rules that the config enables.
        with directory() as root:
            output = SarifFormat(Config(root=root, enable=[], disable=[]))
            output.result(Result(root / "a.py", None))
            end = output.end()
        assert end is not None
        [run] = json.loads(end)["runs"]
        [invocation] = run["invocations"]
        expected = {"executionSuccessful": True, "toolExecutionNotifications": []}
        self.assertEqual(invocation, expected)
        self.assertEqual((run["tool"]["driver"]["rules"], run["results"]), ([], []))

    def test_sarif_rules_that_cannot_be_loaded(self) -> None:
        # The error is the result of each file: the rules reported, by name.
        error = ConfigError("no such rule")
        with (
            directory() as root,
            patch.object(documents, "load_rules", side_effect=error),
        ):
            output = SarifFormat(Config())
            output.result(Result(root / "a.py", Violation("First", FIRST, "m", False)))
            end = output.end()
        assert end is not None
        [run] = json.loads(end)["runs"]
        ids = [rule["id"] for rule in run["tool"]["driver"]["rules"]]
        self.assertEqual(ids, ["First"])

    def test_machine_readable(self) -> None:
        class One:
            MACHINE_READABLE = 1

        cases = (
            (None, False),
            (TukuroiFormat(Config()), False),
            # True only, not a value that is true.
            (One(), False),
            (JsonFormat(Config()), True),
            (SarifFormat(Config()), True),
        )
        for output, expected in cases:
            with self.subTest(type(output).__name__):
                self.assertIs(machine_readable(output), expected)  # type: ignore[arg-type]

    def test_metrics_hook(self) -> None:
        cases = (
            # (--print-metrics, the format, fix -, the hook)
            (False, TukuroiFormat, False, None),
            (False, JsonFormat, False, None),
            (False, TukuroiFormat, True, None),
            (True, TukuroiFormat, False, print),
            (True, JsonFormat, False, print_to_stderr),
            # stdout is the fixed source (#196).
            (True, TukuroiFormat, True, print_to_stderr),
        )
        for flag, kind, stdin, expected in cases:
            with self.subTest(flag=flag, kind=kind.__name__, stdin=stdin):
                options = Options(print_metrics=flag)
                hook = metrics_hook(options, kind(Config()), stdin=stdin)
                self.assertIs(hook, expected)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            print_to_stderr({"Count.Total": 1})
        self.assertEqual((out.getvalue(), err.getvalue()), ("", "{'Count.Total': 1}\n"))


class DocumentsCliTest(TestCase):
    maxDiff = None

    def test_lint(self) -> None:
        # The document alone on stdout: the diffs and the errors on stderr.
        files = {"pyproject.toml": CONFIG, "t.py": FIXABLE, "broken.py": BROKEN}
        diff = "--- a/t.py\n+++ b/t.py\n"
        for name in ("json", "sarif", "JSON"):
            with self.subTest(name):
                result = invoke(files, ["-o", name, "lint", "--diff"])
                found = json.loads(result.stdout)
                self.assertEqual(result.exit_code, 3)
                self.assertIn(diff, result.stderr)
                self.assertIn("broken.py: EXCEPTION: ", result.stderr)
                if name == "sarif":
                    [run] = found["runs"]
                    self.assertEqual([r["ruleId"] for r in run["results"]], [NA])
                    self.assertFalse(run["invocations"][0]["executionSuccessful"])
                else:
                    self.assertEqual(found["files"], ["broken.py", "t.py"])
                    self.assertEqual(len(found["errors"]), 1)

    def test_lint_by_config(self) -> None:
        files = {
            "pyproject.toml": CONFIG + 'output-format = "json"\n',
            "t.py": FIXABLE,
        }
        result = invoke(files, ["--print-metrics", "lint", "t.py"])
        found = json.loads(result.stdout)
        self.assertEqual([v["rule"] for v in found["violations"]], [NA])
        # The metrics on stderr, before the summary.
        self.assertRegex(result.stderr, r"\A\{'Count.Total': 1, .*\}\n")
        self.assertTrue(result.stderr.endswith(DIRTY_A), result.stderr)
        self.assertEqual(result.exit_code, 1)

    def test_fix(self) -> None:
        files = {"pyproject.toml": CONFIG, "t.py": FIXABLE}
        with self.subTest("automatic"):
            result = invoke(files, ["-o", "json", "fix", "--automatic", "t.py"])
            found = json.loads(result.stdout)
            self.assertEqual(
                found["fixed"], [{"path": "t.py", "applied": 1, "remaining": 0}]
            )
            self.assertEqual(result.files["t.py"], FIXED)
            self.assertEqual(result.stderr, DIRTY_F)
            self.assertEqual(result.exit_code, 0)
        with self.subTest("interactive"):
            # The diff and the prompt on stderr.
            result = invoke(files, ["-o", "json", "fix", "t.py"], stdin="y\n")
            found = json.loads(result.stdout)
            self.assertEqual(len(found["fixed"]), 1)
            self.assertIn("--- a/t.py\n", result.stderr)
            self.assertIn("Apply autofix? (y, n, q) [y]: ", result.stderr)
            self.assertEqual(result.files["t.py"], FIXED)

    def test_fix_stdin(self) -> None:
        # stdout is the fixed source: a usage error, before anything is read.
        files = {"pyproject.toml": CONFIG + 'output-format = "sarif"\n'}
        result = invoke(files, ["fix", "-", "t.py"], stdin=FIXABLE)
        error = (
            "Error: 'fix -' prints the fixed source on stdout: output-format"
            " 'sarif' cannot print there\n"
        )
        self.assertTrue(result.stderr.endswith(error), result.stderr)
        self.assertEqual((result.stdout, result.exit_code), ("", 2))
