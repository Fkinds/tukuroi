# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import json
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from unittest import TestCase

import pygls.uris as Uri
from click.testing import CliRunner

from fixit import __version__
from fixit.cli import main


class SmokeTest(TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_cli_without_args_shows_help(self) -> None:
        result = self.runner.invoke(main, [])

        self.assertEqual(result.exit_code, 0)
        self.assertRegex(result.stdout, r"^Usage: ")
        self.assertIn("Commands:", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_cli_options_without_command_fail(self) -> None:
        result = self.runner.invoke(main, ["--debug"])

        self.assertEqual(result.exit_code, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Error: Missing command.", result.stderr)

    def test_cli_version(self) -> None:
        result = self.runner.invoke(main, ["--version"])
        expected = rf"fixit, version {__version__}"
        self.assertIn(expected, result.stdout)

    def test_cli_debug_flag_default(self) -> None:
        # --debug/--quiet must stay None when neither is given, so that the
        # default log level is used (click 8.2.2 returned False here).
        for args, expected in (
            (["lint"], None),
            (["--debug", "lint"], True),
            (["--quiet", "lint"], False),
        ):
            with (
                self.subTest(args=args),
                main.make_context("fixit", args) as ctx,
            ):
                self.assertIs(ctx.params["debug"], expected)

    def test_file_with_formatting(self) -> None:
        # Uses the rules of the new engine (#21), which formats a fixed file
        # with ruff format: the blank lines before `def`.
        content = dedent(
            """\
                import foo
                import bar

                def func():
                    self.assertTrue(a in b)
            """
        )
        expected_fix = dedent(
            """\
                import foo
                import bar


                def func():
                    self.assertIn(a, b)
            """
        )
        # The message has a line break.
        reported = r"(?s)file\.py@\d+:\d+ UseAssertIn: .+ \(has autofix\)"
        with TemporaryDirectory() as td:
            tdp = Path(td).resolve()
            path = tdp / "file.py"

            with self.subTest("linting"):
                path.write_text(content)
                result = self.runner.invoke(
                    main, ["lint", path.as_posix()], catch_exceptions=False
                )

                self.assertNotEqual(result.stdout, "")
                self.assertNotEqual(result.exit_code, 0)
                self.assertRegex(result.stdout, reported)
                self.assertEqual(content, path.read_text(), "file unexpectedly changed")

            with self.subTest("fixing"):
                path.write_text(content)
                result = self.runner.invoke(
                    main,
                    ["fix", "--automatic", path.as_posix()],
                    catch_exceptions=False,
                )

                self.assertNotEqual(result.stdout, "")
                self.assertEqual(result.exit_code, 0)
                self.assertRegex(result.stdout, reported)
                self.assertEqual(
                    expected_fix, path.read_text(), "unexpected file output"
                )

            with self.subTest("linting via stdin"):
                result = self.runner.invoke(
                    main,
                    ["lint", "-", path.as_posix()],
                    input=content,
                    catch_exceptions=False,
                )

                self.assertNotEqual(result.stdout, "")
                self.assertNotEqual(result.exit_code, 0)
                self.assertRegex(result.stdout, reported)

            with self.subTest("fixing via stdin"):
                result = self.runner.invoke(
                    main,
                    ["fix", "-", path.as_posix()],
                    input=content,
                    catch_exceptions=False,
                )

                self.assertEqual(result.exit_code, 0)
                self.assertEqual(expected_fix, result.stdout, "unexpected stdout")

            with self.subTest("LSP"):
                path.write_text(content)
                uri = Uri.from_fs_path(path.as_posix())

                initialize = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"capabilities":{}}}'

                did_open_template = '{{"jsonrpc":"2.0","id":1,"method":"textDocument/didOpen","params":{{"textDocument":{{"uri":{uri},"languageId":"python","version":0,"text":{content}}}}}}}'
                did_open = did_open_template.format(
                    uri=json.dumps(uri), content=json.dumps(content)
                )

                def payload(content: str) -> str:
                    return f"Content-Length: {len(content)}\r\n\r\n{content}"

                # The exit code is 0 after shutdown only (LSP 3.17, #96). Not
                # "exit": the server closes stdout, which click flushes after.
                shutdown = '{"jsonrpc":"2.0","id":2,"method":"shutdown"}'
                messages = (initialize, did_open, shutdown)
                result = self.runner.invoke(
                    main,
                    ["lsp", "--debounce-interval", "0"],
                    input="".join(map(payload, messages)),
                    catch_exceptions=False,
                )

                self.assertEqual(result.exit_code, 0)
                self.assertRegex(
                    result.stdout,
                    r"file\.py\".+\"range\".+\"start\".+\"end\".+\"severity\": 2, \"code\": \"UseAssertIn\", \"source\": \"fixit\"",
                )

    def test_this_file_is_clean(self) -> None:
        path = Path(__file__).resolve().as_posix()
        result = self.runner.invoke(main, ["lint", path], catch_exceptions=False)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.exit_code, 0)

    def test_this_project_is_clean(self) -> None:
        project_dir = Path(__file__).resolve().parent.parent.as_posix()
        result = self.runner.invoke(main, ["lint", project_dir], catch_exceptions=False)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.exit_code, 0)

    def test_directory_with_violations(self) -> None:
        with TemporaryDirectory() as td:
            tdp = Path(td).resolve()
            (tdp / "clean.py").write_text("name = 'Kirby'\nprint(f'hello {name}')")
            (tdp / "dirty.py").write_text("name = 'Kirby'\nif True:\n    pass\n")

            result = self.runner.invoke(main, ["lint", td])
            self.assertIn("dirty.py@2:0 NoStaticIfCondition:", result.stdout)
            self.assertEqual(result.exit_code, 1)

    def test_directory_with_errors(self) -> None:
        with TemporaryDirectory() as td:
            tdp = Path(td).resolve()
            (tdp / "clean.py").write_text("name = 'Kirby'\nprint(f'hello {name}')")
            (tdp / "broken.py").write_text("print)\n")

            result = self.runner.invoke(main, ["lint", td])
            self.assertIn("broken.py: EXCEPTION: Syntax Error @ 1:", result.stdout)
            self.assertEqual(result.exit_code, 2)

    def test_directory_with_violations_and_errors(self) -> None:
        with TemporaryDirectory() as td:
            tdp = Path(td).resolve()
            (tdp / "clean.py").write_text("name = 'Kirby'\nprint(f'hello {name}')")
            (tdp / "dirty.py").write_text("name = 'Kirby'\nif True:\n    pass\n")
            (tdp / "broken.py").write_text("print)\n")

            result = self.runner.invoke(main, ["lint", td])
            self.assertIn("dirty.py@2:0 NoStaticIfCondition:", result.stdout)
            self.assertIn("broken.py: EXCEPTION: Syntax Error @ 1:", result.stdout)
            self.assertEqual(result.exit_code, 3)

    def test_directory_with_autofixes(self) -> None:
        # The fixed files are formatted with ruff format (#21), as clean.py is.
        clean_source = dedent(
            """\
            GLOBAL = "hello"


            def foo():
                self.assertIn(a, b)
                self.assertEqual(x, 3)
            """
        )
        with TemporaryDirectory() as td:
            tdp = Path(td).resolve()
            clean = tdp / "clean.py"
            clean.write_text(clean_source)
            single = tdp / "single.py"
            single.write_text(
                clean_source.replace("assertIn(a, b)", "assertTrue(a in b)")
            )
            multi = tdp / "multi.py"
            multi.write_text(
                clean_source.replace("assertIn(a, b)", "assertTrue(a in b)").replace(
                    "assertEqual(x, 3)", "assertTrue(x, 3)"
                )
            )

            expected = clean.read_text()

            result = self.runner.invoke(main, ["fix", "--automatic", td])
            errors = defaultdict(list)
            for line in result.stdout.splitlines():
                fn, _, error = line.partition("@")
                short, _, _ = error.partition(": ")
                errors[Path(fn)].append(short)

            with self.subTest("clean"):
                self.assertListEqual([], errors[clean])
                self.assertEqual(expected, clean.read_text())

            with self.subTest("single fix"):
                self.assertListEqual(["5:4 UseAssertIn"], sorted(errors[single]))
                self.assertEqual(expected, single.read_text())

            with self.subTest("multiple fixes"):
                self.assertListEqual(
                    ["5:4 UseAssertIn", "6:4 NoAssertTrueForComparisons"],
                    sorted(errors[multi]),
                )
                self.assertEqual(expected, multi.read_text())

    def test_lint_directory_with_no_rules_enabled(self) -> None:
        content = dedent(
            """\
                import foo
                import bar

                def func():
                    value = f"hello world"
            """
        )
        with self.subTest("lint"), TemporaryDirectory() as td:
            tdp = Path(td).resolve()
            path = tdp / "file.py"

            (tdp / "pyproject.toml").write_text(
                "[tool.fixit]\ndisable=['fixit.rules']\n"
            )

            path.write_text(content)
            result = self.runner.invoke(
                main,
                ["lint", path.as_posix()],
                catch_exceptions=False,
            )

            self.assertEqual(result.stdout, "")
            self.assertEqual(result.exit_code, 0)

        with self.subTest("fix"), TemporaryDirectory() as td:
            tdp = Path(td).resolve()
            path = tdp / "file.py"

            (tdp / "pyproject.toml").write_text(
                "[tool.fixit]\ndisable=['fixit.rules']\n"
            )

            path.write_text(content)
            result = self.runner.invoke(
                main,
                ["fix", "--automatic", path.as_posix()],
                catch_exceptions=False,
            )

            self.assertEqual(result.stdout, "")
            self.assertEqual(result.exit_code, 0)
