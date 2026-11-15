# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.pool``: the process pool of ``lint``, when a file ends the
process that lints it (#94), and the log records of its processes (#209).
"""

import logging
import multiprocessing
import os
import signal
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Sequence
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest import TestCase, skipUnless

from ..core import loader
from ..ftypes import Error, Result
from ..pool import (
    _PROCESS,
    BROKEN,
    LintPool,
    LogAddress,
    _ended,
    _level,
    _logs_here,
    _receive,
    _send_logs,
)
from .core_loader import new_process

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


def logs(path: Path) -> list[Result]:
    """
    A clean result, after the logs of a process that lints ``path``: a debug
    record and a warning, with the process, a warning given once, and for
    ``error...`` an exception. A file named ``exit...`` then ends the process.
    """
    log = logging.getLogger("tukuroi.tests.pool")
    log.debug("debug %s", path.name)
    log.warning("warning %s %d", path.name, os.getpid())
    loader.WARNINGS.warn("once")
    if path.stem.startswith("error"):
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("error %s", path.name)
    if path.stem.startswith("exit"):
        os._exit(3)
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
                for path, rs in LintPool(lint, workers=2).run(
                    [root / name for name in names]
                )
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

    def test_negative_status_that_is_not_a_signal(self) -> None:
        # As on Windows, where a status is not a signal (#116).
        status = "the process that linted the file exited with status -999"
        self.assertEqual(_ended(-999), Error(BROKEN, status))

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


class PoolLogsTest(TestCase):
    """The log records of the processes, handled by the one that runs the pool."""

    maxDiff = None

    def run_pool(self, names: Sequence[str], level: int = logging.WARNING) -> list[str]:
        """
        The messages of the records that the processes of a pool of two log as
        they lint ``names``, with tukuroi.tests.pool at ``level`` here, in a
        new process: of the loggers ``tukuroi.config`` and
        ``tukuroi.tests.pool``, in order.
        """
        with (
            TemporaryDirectory() as td,
            new_process(),
            self.assertLogs("tukuroi", logging.DEBUG) as caught,
        ):
            logging.getLogger("tukuroi").warning("start")
            logging.getLogger("tukuroi.tests.pool").setLevel(level)
            try:
                paths = [Path(td) / name for name in names]
                for _ in LintPool(logs, workers=2).run(paths):
                    pass
            finally:
                logging.getLogger("tukuroi.tests.pool").setLevel(logging.NOTSET)
        return sorted(r.getMessage() for r in caught.records[1:])

    def test_records(self) -> None:
        # As if logged here: at the levels of the loggers here.
        messages = self.run_pool(["a.py", "b.py", "c.py"])
        found = [m.rsplit(" ", 1)[0] for m in messages]
        self.assertEqual(
            found, ["once", "warning a.py", "warning b.py", "warning c.py"]
        )
        debug = self.run_pool(["a.py"], logging.DEBUG)
        self.assertIn("debug a.py", debug)

    def test_once(self) -> None:
        # Once in all the processes, and not again if this one gave it.
        names = [f"f{i}.py" for i in range(6)]
        self.assertEqual(self.run_pool(names).count("once"), 1)
        with (
            TemporaryDirectory() as td,
            new_process(),
            self.assertLogs("tukuroi") as caught,
        ):
            loader.WARNINGS.warn("once")
            for _ in LintPool(logs, workers=2).run([Path(td) / n for n in names]):
                pass
        self.assertEqual([r.getMessage() for r in caught.records].count("once"), 1)

    def test_once_under_a_higher_level(self) -> None:
        # Given, but not shown, as in this process.
        with (
            TemporaryDirectory() as td,
            new_process(),
            self.assertNoLogs("tukuroi.config", logging.WARNING),
        ):
            logging.getLogger("tukuroi.config").setLevel(logging.ERROR)
            try:
                for _ in LintPool(logs, workers=2).run([Path(td) / "a.py"]):
                    pass
            finally:
                logging.getLogger("tukuroi.config").setLevel(logging.NOTSET)
            self.assertEqual(loader.WARNINGS.given, {"once"})

    def test_traceback(self) -> None:
        [error] = [m for m in self.run_pool(["error.py"]) if m.startswith("error")]
        self.assertTrue(error.startswith("error error.py\nTraceback"), error)
        self.assertIn("ValueError: boom", error)

    def test_processes_of_their_own(self) -> None:
        # The file that breaks the pool is linted again in a process of its
        # own, which sends its records too.
        messages = self.run_pool(["exit.py", "a.py"])
        processes = {m.split()[2] for m in messages if m.startswith("warning exit.py")}
        self.assertEqual(len(processes), 2)

    def test_lowest_level(self) -> None:
        cases = (
            # (logger, level, lowest)
            ("", logging.WARNING, logging.WARNING),
            ("", logging.DEBUG, logging.DEBUG),
            ("tukuroi.tests.pool.level", logging.INFO, logging.INFO),
            ("tukuroi.tests.pool.level", logging.CRITICAL, logging.WARNING),
        )
        root = logging.getLogger()
        before = root.level
        for name, level, lowest in cases:
            with self.subTest(name or "root", level=level):
                logger = logging.getLogger(name) if name else root
                logger.setLevel(level)
                try:
                    self.assertEqual(_level(), lowest)
                finally:
                    logger.setLevel(before if logger is root else logging.NOTSET)

    def test_unreadable_record(self) -> None:
        # Left out with a warning: the next one is read.
        reader, writer = multiprocessing.Pipe(duplex=False)
        record = logging.makeLogRecord(
            {"name": "tukuroi.tests.pool", "levelno": logging.WARNING, "msg": "next"}
        )
        writer.send_bytes(b"not a pickle")
        writer.send(record)
        writer.close()
        with self.assertLogs("tukuroi", logging.WARNING) as caught:
            _receive(reader)
        unreadable, after = [r.getMessage() for r in caught.records]
        cannot = "A log record of a process cannot be read: UnpicklingError("
        self.assertTrue(unreadable.startswith(cannot), unreadable)
        self.assertEqual(after, "next")

    def test_another_key(self) -> None:
        # A process without the key cannot send: the others still can.
        record = logging.makeLogRecord(
            {"name": "tukuroi.tests.pool", "levelno": logging.WARNING, "msg": "sent"}
        )
        with (
            self.assertLogs("tukuroi.tests.pool", logging.WARNING) as caught,
            _logs_here() as here,
        ):
            with self.assertRaises(AuthenticationError):
                Client(here.address, authkey=b"another key")
            # One that ends before it says what it is.
            Client(here.address, authkey=here.authkey).close()
            with Client(here.address, authkey=here.authkey) as connection:
                connection.send(_PROCESS)
                connection.send(record)
        # The last one, right before the end: its record is not lost.
        self.assertEqual([r.getMessage() for r in caught.records], ["sent"])

    def test_processes_connect_at_once(self) -> None:
        # As those of a pool, as it starts: none is refused (#209).
        refused: list[OSError] = []

        def connect(here: LogAddress) -> None:
            try:
                with Client(here.address, authkey=here.authkey) as connection:
                    connection.send(_PROCESS)
            except OSError as error:
                refused.append(error)

        with _logs_here() as here:
            threads = [Thread(target=connect, args=(here,)) for _ in range(32)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(refused, [])

    def test_cannot_connect(self) -> None:
        # The process still lints, with its logging as it was.
        root = logging.getLogger()
        handlers = root.handlers[:]
        nowhere = LogAddress(str(Path(__file__).parent / "nowhere"), b"", logging.DEBUG)
        with self.assertLogs("tukuroi.pool", logging.WARNING) as caught:
            _send_logs(nowhere)
        [message] = [r.getMessage() for r in caught.records]
        self.assertTrue(message.startswith("The logs of this process cannot be sent:"))
        self.assertEqual(root.handlers, handlers)


class PoolCliTest(TestCase):
    """``tukuroi lint`` of files in a pool, in a process of its own (#209)."""

    def lint(self, files: dict[str, str], *flags: str) -> list[str]:
        """
        The lines of stderr of the logs below, with or without the level and
        the logger, and of the end: not those of coverage, which may warn too.
        """
        env = {k: v for k, v in os.environ.items() if k != "TUKUROI_CUSTOM_RULES"}
        with TemporaryDirectory() as td:
            cwd = Path(td)
            (cwd / ".git").mkdir()
            for name, text in files.items():
                (cwd / name).write_text(text)
            result = subprocess.run(
                [sys.executable, "-m", "tukuroi", *flags, "lint", "."],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        words = ("invalid lint-ignore directive", "Skipped rules", "🧼")
        lines = result.stderr.splitlines()
        return [line for line in lines if any(word in line for word in words)]

    def test_logs(self) -> None:
        files = {f"t{i}.py": "x = 1\n" for i in range(16)}
        files["pyproject.toml"] = (
            '[tool.tukuroi]\nroot = true\nenable = ["tukuroi.rules", "nope.rules"]\n'
        )
        files["a.py"] = "x = 1  # lint-ignore:\n"
        invalid = "WARNING:tukuroi.api:a.py:1: invalid lint-ignore directive"
        skipped = "WARNING:tukuroi.config:Skipped rules 'nope.rules': custom rules are turned off"
        clean = "🧼 17 files clean 🧼"
        cases = (
            # (flags, lines)
            (["--no-custom-rules"], [skipped, invalid, clean]),
            (["--no-custom-rules", "--quiet"], [clean]),
        )
        for flags, expected in cases:
            with self.subTest(flags):
                self.assertEqual(sorted(self.lint(files, *flags)), sorted(expected))
