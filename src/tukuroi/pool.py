# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The process pool of ``lint``, for two files or more.

A rule can end the process that lints a file: ``os._exit``, a crash, a kill.
The pool then breaks, and the results of the files in it are lost (#94). Those
files are linted again, each in a process of its own: a file that ends its
process again gets an error, the others their results. A new pool lints the
rest.

The processes do not have the logging of the process that runs the pool, which
spawns them. Each one sends its log records to it, on a connection of its own,
and that process handles them as its own (#209): with its levels, its handlers
and their format, and a warning given once (:class:`~tukuroi.core.loader.OnceLog`)
once there too. A queue of :mod:`multiprocessing` would be one for all, with a
lock that a process could take with it as it ends.
"""

import logging
import multiprocessing
import os
import signal
import sys
import threading
from collections import deque
from collections.abc import Callable, Generator, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from dataclasses import dataclass, field
from logging.handlers import QueueHandler
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Connection, Listener
from multiprocessing.process import BaseProcess
from pathlib import Path

from .core import loader
from .ftypes import Error, Result

Lint = Callable[[Path], list[Result]]
Done = Iterator[tuple[Path, list[Result]]]

# The files in the pool at a time, for each of its processes: as fast as all
# of them at once (600 files, 12 processes), and few to lint again when the
# pool breaks.
FILES_PER_PROCESS = 4

# The exception that a file of a broken pool gets.
BROKEN = f"{BrokenProcessPool.__module__}.{BrokenProcessPool.__qualname__}"

# The same on Linux, macOS and Windows.
_CONTEXT = multiprocessing.get_context("spawn")

LOG = logging.getLogger(__name__)


def _default_workers() -> int:
    """The processes of a pool, as ``ProcessPoolExecutor`` chooses them."""
    count = os.process_cpu_count() or 1
    return min(count, 61) if sys.platform == "win32" else count


@dataclass(frozen=True)
class LintPool:
    """
    Lints files with ``lint`` in a process pool of ``workers`` processes (by
    default, as many as ``ProcessPoolExecutor`` makes). ``lint`` must pickle. A
    run makes a new pool for each round: a pool that breaks is not used again
    (#94).
    """

    lint: Lint
    workers: int = field(default_factory=_default_workers)

    def run(self, paths: Iterable[Path]) -> Done:
        """
        Lint each of ``paths``, and yield it with its results as they come. The
        log records of the processes are handled before the end.
        """
        todo = deque(paths)
        with _logs_here() as logs:
            while todo:
                lost = yield from self._pool(todo, logs)
                yield from self._alone(lost, logs)

    def _pool(
        self, todo: deque[Path], logs: LogAddress
    ) -> Generator[tuple[Path, list[Result]], None, list[Path]]:
        """
        Lint the files of ``todo`` in a new pool, until there are none or the
        pool breaks; return the files whose results the pool lost.
        """
        running: dict[Future[list[Result]], Path] = {}
        lost: list[Path] = []
        with ProcessPoolExecutor(
            self.workers,
            mp_context=_CONTEXT,
            initializer=_send_logs,
            initargs=(logs,),
        ) as pool:
            while (todo or running) and not lost:
                while todo and len(running) < FILES_PER_PROCESS * self.workers:
                    path = todo.popleft()
                    running[pool.submit(self.lint, path)] = path
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                if any(isinstance(f.exception(), BrokenProcessPool) for f in done):
                    # The other files in the pool are lost with it.
                    done, _ = wait(running)
                for future in done:
                    path = running.pop(future)
                    if isinstance(future.exception(), BrokenProcessPool):
                        lost.append(path)
                    else:
                        yield path, future.result()
        return lost

    def _alone(self, paths: list[Path], logs: LogAddress) -> Done:
        """Lint each of ``paths`` in a process of its own, ``workers`` at a time."""
        for start in range(0, len(paths), self.workers):
            batch = paths[start : start + self.workers]
            started = [(path, *_start(path, self.lint, logs)) for path in batch]
            for path, process, reader in started:
                yield path, _finish(path, process, reader)


def _start(path: Path, lint: Lint, logs: LogAddress) -> tuple[BaseProcess, Connection]:
    reader, writer = _CONTEXT.Pipe(duplex=False)
    process = _CONTEXT.Process(target=_send, args=(path, lint, writer, logs))
    process.start()
    # Only the process writes: the reader ends when the process does.
    writer.close()
    return process, reader


def _send(path: Path, lint: Lint, writer: Connection, logs: LogAddress) -> None:
    _send_logs(logs)
    writer.send(lint(path))


def _finish(path: Path, process: BaseProcess, reader: Connection) -> list[Result]:
    """The results that the process of ``path`` sent, or how it ended."""
    results: list[Result] | None = None
    try:
        # Before join: the process waits until its results are read.
        results = reader.recv()
    except EOFError:
        pass  # it ended without them
    finally:
        reader.close()
    process.join()
    if results is None:
        return [Result(path, violation=None, error=_ended(process.exitcode))]
    return results


def _ended(code: int | None) -> Error:
    """How a process ended, as ``subprocess.CalledProcessError`` says it."""
    if code is not None and code < 0:
        try:
            # On POSIX, the signal that ended it.
            name = repr(signal.Signals(-code))
            return Error(BROKEN, f"the process that linted the file died with {name}")
        except ValueError:
            pass  # not a signal (Windows)
    return Error(BROKEN, f"the process that linted the file exited with status {code}")


@dataclass(frozen=True)
class LogAddress:
    """
    Where a process of a pool sends its log records (#209): the address of the
    listener of the process that runs the pool, its key, and the lowest level
    that that process logs.
    """

    address: str | tuple[str, int]
    authkey: bytes
    level: int


# The first message on a connection to the listener of the records: from a
# process of a pool, or from the end of the block of :func:`_logs_here`.
_PROCESS, _END = "process", "end"


def _send_logs(logs: LogAddress) -> None:
    """In a process of a pool: send its log records to the process that runs it."""
    connection = Client(logs.address, authkey=logs.authkey)
    connection.send(_PROCESS)
    root = logging.getLogger()
    root.handlers[:] = [QueueHandler(_Sender(connection))]
    root.setLevel(logs.level)


@dataclass(frozen=True)
class _Sender:
    """
    The queue of a :class:`~logging.handlers.QueueHandler`: it sends each record
    on ``connection``, with its message and its traceback in text.
    """

    connection: Connection

    def put_nowait(self, record: logging.LogRecord) -> None:
        self.connection.send(record)

    def get(self) -> logging.LogRecord:
        raise AssertionError("the process that runs the pool reads the records")


def _level() -> int:
    """
    The lowest level that a logger of this process logs from: that of its root,
    or of another logger that has a level of its own.
    """
    loggers = logging.Logger.manager.loggerDict.values()
    levels = [x.level for x in loggers if isinstance(x, logging.Logger) and x.level]
    return min([logging.getLogger().getEffectiveLevel(), *levels])


@contextmanager
def _logs_here() -> Iterator[LogAddress]:
    """
    Where the processes of a pool send their log records, which a thread for
    each process handles here (:func:`_receive`). At the end of the block, the
    processes have ended: their records are handled, and the threads end.

    A process connects before it ends, and the end connects after: the thread
    that accepts the connections ends with the last one, which says so.
    """
    authkey = os.urandom(32)
    listener = Listener(authkey=authkey)
    logs = LogAddress(listener.address, authkey, _level())
    readers: list[threading.Thread] = []

    def accept() -> None:
        while True:
            try:
                connection = listener.accept()
            except OSError, EOFError, AuthenticationError:
                continue  # a process that ended as it connected, or a stranger
            try:
                first = connection.recv()
            except EOFError, OSError:
                connection.close()
                continue  # a process that ended as it began
            if first == _END:
                connection.close()
                return
            reader = threading.Thread(target=_receive, args=(connection,))
            reader.start()
            readers.append(reader)

    acceptor = threading.Thread(target=accept)
    acceptor.start()
    try:
        yield logs
    finally:
        with Client(logs.address, authkey=authkey) as end:
            end.send(_END)
        acceptor.join()
        for reader in readers:
            reader.join()
        listener.close()


def _receive(connection: Connection) -> None:
    """
    Handle each record that comes on ``connection`` as if it were logged here,
    until its process ends: with the levels of the loggers of this process, and
    a warning of :class:`~tukuroi.core.loader.OnceLog` once. A record that
    cannot be read is a warning, and the others are still read: a process that
    sends waits until they are.
    """
    with connection:
        while True:
            try:
                record = connection.recv()
            except EOFError, OSError:
                return  # the process ended, maybe as it sent
            # Unpickling a record can raise any exception, such as that of a
            # class that this process cannot import.
            except Exception as error:  # noqa: BLE001
                LOG.warning("A log record of a process cannot be read: %r", error)
                continue
            if getattr(record, loader.ONCE, False):
                loader.WARNINGS.handle(record)
                continue
            logger = logging.getLogger(record.name)
            if logger.isEnabledFor(record.levelno):
                logger.handle(record)
