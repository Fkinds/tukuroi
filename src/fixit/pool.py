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
"""

import multiprocessing
import os
import signal
import sys
from collections import deque
from collections.abc import Callable, Generator, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path

from .ftypes import Error, Result

Lint = Callable[[Path], list[Result]]
Done = Iterator[tuple[Path, list[Result]]]

# The files in the pool at a time, for each of its processes: as fast as all
# of them at once (600 files, 12 processes), and few to lint again when the
# pool breaks.
FILES_PER_PROCESS = 4

# The exception that a file of a broken pool gets.
BROKEN = f"{BrokenProcessPool.__module__}.{BrokenProcessPool.__qualname__}"

# As trailrunner: the same on Linux, macOS and Windows.
_CONTEXT = multiprocessing.get_context("spawn")


def run(paths: Iterable[Path], lint: Lint, *, workers: int = 0) -> Done:
    """
    ``lint`` each of ``paths`` in a process pool of ``workers`` processes
    (``ProcessPoolExecutor``'s default if 0), and yield each path with its
    results as they come. ``lint`` must pickle.
    """
    workers = workers or _default_workers()
    todo = deque(paths)
    while todo:
        lost = yield from _pool(todo, lint, workers)
        yield from _alone(lost, lint, workers)


def _default_workers() -> int:
    """The processes of a pool, as ``ProcessPoolExecutor`` chooses them."""
    count = os.process_cpu_count() or 1
    return min(count, 61) if sys.platform == "win32" else count


def _pool(
    todo: deque[Path], lint: Lint, workers: int
) -> Generator[tuple[Path, list[Result]], None, list[Path]]:
    """
    Lint the files of ``todo`` in a new pool, until there are none or the
    pool breaks; return the files whose results the pool lost.
    """
    running: dict[Future[list[Result]], Path] = {}
    lost: list[Path] = []
    with ProcessPoolExecutor(workers, mp_context=_CONTEXT) as pool:
        while (todo or running) and not lost:
            while todo and len(running) < FILES_PER_PROCESS * workers:
                path = todo.popleft()
                running[pool.submit(lint, path)] = path
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


def _alone(paths: list[Path], lint: Lint, workers: int) -> Done:
    """Lint each of ``paths`` in a process of its own, ``workers`` at a time."""
    for start in range(0, len(paths), workers):
        batch = paths[start : start + workers]
        started = [(path, *_start(path, lint)) for path in batch]
        for path, process, reader in started:
            yield path, _finish(path, process, reader)


def _start(path: Path, lint: Lint) -> tuple[BaseProcess, Connection]:
    reader, writer = _CONTEXT.Pipe(duplex=False)
    process = _CONTEXT.Process(target=_send, args=(path, lint, writer))
    process.start()
    # Only the process writes: the reader ends when the process does.
    writer.close()
    return process, reader


def _send(path: Path, lint: Lint, writer: Connection) -> None:
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
