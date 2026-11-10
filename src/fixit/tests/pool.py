# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``fixit.pool``: the process pool of ``lint``, when a file ends the
process that lints it (#94).
"""

import os
import signal
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from ..ftypes import Error, Result
from ..pool import BROKEN, run

EXIT = "the process that linted the file exited with status 3"


def lint(path: Path) -> list[Result]:
    """
    A clean result, after a mark of the call next to ``path``. A file named
    ``exit...`` ends the process with status 3, ``kill...`` with SIGKILL, and
    ``slow...`` takes 50 ms.
    """
    (path.parent / f"{path.name}.{os.getpid()}").touch()
    if path.stem.startswith("slow"):
        time.sleep(0.05)
    if path.stem.startswith("exit"):
        os._exit(3)
    if path.stem.startswith("kill"):
        os.kill(os.getpid(), signal.SIGKILL)
    return [Result(path, violation=None)]


def clean(name: str) -> list[Result]:
    return [Result(Path(name), violation=None)]


def broken(name: str, message: str = EXIT) -> list[Result]:
    return [Result(Path(name), violation=None, error=Error(BROKEN, message))]


class PoolTest(TestCase):
    maxDiff = None

    def run_pool(
        self, names: Sequence[str]
    ) -> tuple[dict[str, list[Result]], list[tuple[str, str]]]:
        """
        The results of each file, by name, with two processes (eight files in
        the pool at a time); and each call of ``lint``: the file and the
        process.
        """
        with TemporaryDirectory() as td:
            root = Path(td)
            found = {
                path.name: [Result(Path(r.path.name), r.violation, r.error) for r in rs]
                for path, rs in run([root / name for name in names], lint, workers=2)
            }
            calls = [(mark.stem, mark.suffix) for mark in root.iterdir()]
        return found, calls

    def test_no_file_ends_its_process(self) -> None:
        names = [f"f{i}.py" for i in range(10)]
        found, calls = self.run_pool(names)
        self.assertEqual(found, {name: clean(name) for name in names})
        self.assertEqual(Counter(name for name, _ in calls), Counter(names))

    def test_exit(self) -> None:
        found, _ = self.run_pool(["a.py", "exit.py", "b.py"])
        expected = {
            "a.py": clean("a.py"),
            "exit.py": broken("exit.py"),
            "b.py": clean("b.py"),
        }
        self.assertEqual(found, expected)

    @skipUnless(hasattr(signal, "SIGKILL"), "POSIX")
    def test_signal(self) -> None:
        found, _ = self.run_pool(["a.py", "kill.py"])
        died = "the process that linted the file died with <Signals.SIGKILL: 9>"
        self.assertEqual(
            found, {"a.py": clean("a.py"), "kill.py": broken("kill.py", died)}
        )

    def test_lint_again_only_the_files_in_the_pool(self) -> None:
        # The first file breaks the pool: only the eight files in it then are
        # linted again, each in a process of its own, before a new pool lints
        # the rest. The pool sees that it broke when no result is coming: the
        # other files are slow.
        names = ["exit.py"] + [f"slow{i:02}.py" for i in range(40)]
        found, calls = self.run_pool(names)
        expected = {name: clean(name) for name in names} | {
            "exit.py": broken("exit.py")
        }
        self.assertEqual(found, expected)
        # Two pools of two processes, and a process for each of the eight.
        self.assertLessEqual(len({process for _, process in calls}), 2 + 8 + 2)

    def test_two_files_end_their_processes(self) -> None:
        names = [f"f{i}.py" for i in range(10)] + ["exit1.py", "exit2.py"]
        found, _ = self.run_pool(names)
        expected = {name: clean(name) for name in names}
        expected |= {"exit1.py": broken("exit1.py"), "exit2.py": broken("exit2.py")}
        self.assertEqual(found, expected)
