# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The configs of Fixit that tukuroi does not read (#202): which ones are a
warning, in which directories, and once in a process, by each command that
reads the configs.
"""

import logging
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from .. import config
from ..config import ConfigReader, validate_config
from ..ftypes import Options
from ..util import chdir
from .characterization_cli import invoke
from .characterization_lsp import ROOT, did_open, serve, session
from .core_loader import files, new_process

FIXIT = '[tool.fixit]\nenable = ["fixit.rules"]\n'
TUKUROI = '[tool.tukuroi]\nenable = ["tukuroi.rules"]\n'
SEE = '(see "Coming from Fixit" in the README)'


def table(path: str = "pyproject.toml") -> str:
    """The warning of the ``[tool.fixit]`` of ``path``."""
    return f"{path}: [tool.fixit] is not read: tukuroi reads [tool.tukuroi] {SEE}"


def named(path: str, instead: str) -> str:
    """The warning of ``path``, a ``fixit.toml`` or a ``.fixit.toml``."""
    return f"{path}: not read: tukuroi reads {instead} {SEE}"


class FixitConfigTest(TestCase):
    maxDiff = None

    def warned(
        self,
        tree: Mapping[str, str],
        path: str = "t.py",
        *,
        cwd: str = ".",
        options: Options | None = None,
    ) -> list[str]:
        """
        The warnings of the configs of Fixit for ``path`` in ``tree``, a
        repository, in a new process, with the root of ``tree`` as ``ROOT``.
        """
        with (
            files({".git/HEAD": "", **tree}) as root,
            chdir(root / cwd),
            new_process(),
            self.assertLogs("tukuroi.config", "WARNING") as logs,
        ):
            logging.getLogger("tukuroi.config").warning("start")
            ConfigReader(options).warn_of_fixit(root / path)
        return [r.getMessage().replace(str(root), "ROOT") for r in logs.records[1:]]

    def test_directory(self) -> None:
        cases = (
            # (label, files, warnings)
            ("[tool.fixit]", {"pyproject.toml": FIXIT}, [table()]),
            ("an empty [tool.fixit]", {"pyproject.toml": "[tool.fixit]\n"}, []),
            ("fixit.toml", {"fixit.toml": FIXIT}, [named("fixit.toml", "tukuroi.toml")]),
            (".fixit.toml", {".fixit.toml": FIXIT}, [named(".fixit.toml", ".tukuroi.toml")]),
            ("a fixit.toml without [tool.fixit]", {"fixit.toml": "root = true\n"}, []),
            ("all, by name", {"pyproject.toml": FIXIT, "fixit.toml": FIXIT, ".fixit.toml": FIXIT}, [named("fixit.toml", "tukuroi.toml"), named(".fixit.toml", ".tukuroi.toml"), table()]),
            # A config of tukuroi next to it, even empty, stops the warnings.
            ("and [tool.tukuroi]", {"pyproject.toml": FIXIT + TUKUROI}, []),
            ("and an empty [tool.tukuroi]", {"pyproject.toml": FIXIT + "[tool.tukuroi]\n"}, []),
            ("and an empty tukuroi.toml", {"pyproject.toml": FIXIT, "fixit.toml": FIXIT, "tukuroi.toml": ""}, []),
            ("and an empty .tukuroi.toml", {"fixit.toml": FIXIT, ".tukuroi.toml": ""}, []),
            # Not TOML: not a config of Fixit. read_configs tells of a
            # pyproject.toml, which tukuroi reads.
            ("fixit.toml, not TOML", {"fixit.toml": "[tool.fixit\n"}, []),
            ("pyproject.toml, not TOML", {"pyproject.toml": "[tool.fixit\n", "fixit.toml": FIXIT}, [named("fixit.toml", "tukuroi.toml")]),
            ("tool, not a table", {"pyproject.toml": "tool = 1\n"}, []),
        )  # fmt: skip
        for label, tree, expected in cases:
            with self.subTest(label):
                self.assertEqual(self.warned(tree), expected)

    def test_not_utf_8(self) -> None:
        with files({".git/HEAD": ""}) as root, chdir(root), new_process():
            (root / "fixit.toml").write_bytes(b"[tool.fixit]\nenable = ['\xff']\n")
            with self.assertNoLogs("tukuroi.config", "WARNING"):
                ConfigReader().warn_of_fixit(root / "t.py")

    def test_directories(self) -> None:
        root = "[tool.tukuroi]\nroot = true\n"
        cases = (
            # (label, files, path, warnings)
            ("under the root config", {"pyproject.toml": root, "sub/fixit.toml": FIXIT}, "sub/t.py", [named("sub/fixit.toml", "tukuroi.toml")]),
            ("nearest first", {"fixit.toml": FIXIT, "sub/fixit.toml": FIXIT}, "sub/t.py", [named("sub/fixit.toml", "tukuroi.toml"), named("fixit.toml", "tukuroi.toml")]),
            # Where the search for configs stops: not above.
            ("above the root config", {"fixit.toml": FIXIT, "sub/pyproject.toml": root}, "sub/t.py", []),
            ("above a root tukuroi.toml", {"fixit.toml": FIXIT, "sub/tukuroi.toml": root}, "sub/t.py", []),
            ("above the repository", {"fixit.toml": FIXIT, "sub/.git/HEAD": ""}, "sub/t.py", []),
            # root = true of Fixit, or root = false, does not stop it.
            ("root of Fixit", {"fixit.toml": FIXIT, "sub/pyproject.toml": "[tool.fixit]\nroot = true\n"}, "sub/t.py", [table("sub/pyproject.toml"), named("fixit.toml", "tukuroi.toml")]),
            ("root = false", {"fixit.toml": FIXIT, "sub/pyproject.toml": "[tool.tukuroi]\nroot = false\n"}, "sub/t.py", [named("fixit.toml", "tukuroi.toml")]),
            ("a directory", {"sub/fixit.toml": FIXIT, "sub/t.py": ""}, "sub", [named("sub/fixit.toml", "tukuroi.toml")]),
        )  # fmt: skip
        for label, tree, path, expected in cases:
            with self.subTest(label):
                self.assertEqual(self.warned(tree, path), expected)
        with self.subTest("relative to the current directory, if under it"):
            tree = {"fixit.toml": FIXIT, "sub/t.py": ""}
            found = self.warned(tree, "sub/t.py", cwd="sub")
            self.assertEqual(found, [named("ROOT/fixit.toml", "tukuroi.toml")])

    def test_config_file(self) -> None:
        # Only the config named, as tukuroi reads it.
        cases = (
            # (label, files, warnings)
            ("[tool.fixit]", {"c.toml": FIXIT, "fixit.toml": FIXIT}, [table("c.toml")]),
            ("and [tool.tukuroi]", {"c.toml": FIXIT + "[tool.tukuroi]\n"}, []),
            ("an empty [tool.fixit]", {"c.toml": "[tool.fixit]\n"}, []),
            ("not TOML", {"c.toml": "[tool.fixit\n"}, []),
        )  # fmt: skip
        for label, tree, expected in cases:
            with self.subTest(label):
                options = Options(config_file=Path("c.toml"))
                self.assertEqual(self.warned(tree, options=options), expected)

    def test_once_in_a_process(self) -> None:
        with (
            files({".git/HEAD": "", "fixit.toml": FIXIT}) as root,
            chdir(root),
            new_process(),
            self.assertLogs("tukuroi.config", "WARNING") as logs,
        ):
            reader = ConfigReader()
            reader.warn_of_fixit(root / "t.py")
            reader.warn_of_fixit(root / "sub" / "t.py")
            # A directory is looked in once: a config of Fixit added later is
            # not seen.
            (root / ".fixit.toml").write_text(FIXIT)
            reader.warn_of_fixit(root / "t.py")
            looked = config.FIXIT_CHECK.looked
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(looked, {root: False, root / "sub": False})

    def test_check(self) -> None:
        # lint and fix: the directory of each file, before its config is read.
        tree = {".git/HEAD": "", "fixit.toml": FIXIT, "sub/fixit.toml": FIXIT}
        with (
            files(tree) as root,
            chdir(root),
            new_process(),
            self.assertLogs("tukuroi.config", "WARNING") as logs,
        ):
            ConfigReader().check([root / "t.py", root / "sub" / "t.py"])
        self.assertEqual(
            [r.getMessage() for r in logs.records],
            [
                named("fixit.toml", "tukuroi.toml"),
                named("sub/fixit.toml", "tukuroi.toml"),
            ],
        )

    def test_validate_config(self) -> None:
        with (
            files({".git/HEAD": "", "pyproject.toml": FIXIT}) as root,
            chdir(root),
            new_process(),
            self.assertLogs("tukuroi.config", "WARNING") as logs,
        ):
            errors = validate_config(Path("pyproject.toml"))
        self.assertEqual(errors, [])
        self.assertEqual([r.getMessage() for r in logs.records], [table()])

    def test_commands(self) -> None:
        tree = {"pyproject.toml": FIXIT, "t.py": "x = 1\n"}
        warning = f"WARNING:tukuroi.config:{table()}\n"
        cases = (
            # (command, stderr after the warning)
            (["lint", "t.py"], "🧼 1 file clean 🧼\n"),
            (["fix", "t.py"], "🧼 1 file clean 🧼\n"),
            (["validate-config", "pyproject.toml"], ""),
        )
        for args, after in cases:
            with self.subTest(args[0]):
                self.assertEqual(invoke(tree, args).stderr, warning + after)
        with self.subTest("test"):
            # Before the error of the rules that [tool.fixit] would import.
            result = invoke(tree, ["test", "myrules"])
            self.assertTrue(result.stderr.startswith(f"{warning}Error: "))

    def test_lsp(self) -> None:
        tree = {"pyproject.toml": FIXIT}
        with new_process():
            opened = [
                did_open("x = 1\n", f"{ROOT}/{name}") for name in ("a.py", "b.py")
            ]
            served = serve(tree, session(*opened))
        self.assertEqual(served.stderr, f"WARNING:tukuroi.config:{table()}\n")

    def test_once_with_a_pool(self) -> None:
        # The processes of the pool do not warn again: in a process of its
        # own, as the pool is.
        env = {k: v for k, v in os.environ.items() if k != "TUKUROI_CUSTOM_RULES"}
        with TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / ".git").mkdir()
            (cwd / "pyproject.toml").write_text(FIXIT)
            for n in range(16):
                (cwd / f"t{n}.py").write_text("x = 1\n")
            result = subprocess.run(
                [sys.executable, "-m", "tukuroi", "lint", "."],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        # Under coverage, its processes may print warnings of their own. One
        # of the pool would have no "WARNING:", as it does not set logging up.
        lines = result.stderr.splitlines()
        warnings = [line for line in lines if "is not read" in line]
        self.assertEqual(warnings, [f"WARNING:tukuroi.config:{table()}"])
        self.assertEqual(lines[-1], "🧼 16 files clean 🧼")
        self.assertEqual(result.returncode, 0)
