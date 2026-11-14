# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
ruff for the files that the new engine fixes, when a config chooses it with
``formatter = "ruff"`` (#21, #108): it sorts the imports, then formats (#140).

It runs the ``ruff`` executable of the ``ruff`` package, on the text through
stdin, with ``--stdin-filename``: the settings of ruff for that path (such as
the line length, or the sections of isort) apply. The package is optional
(``tukuroi[ruff]``): it is imported only to format.
"""

import importlib.util
import subprocess
from collections.abc import Sequence
from pathlib import Path


class FormatError(Exception):
    """ruff failed, for example on a syntax error."""


def ruff_installed() -> bool:
    """Whether the ``ruff`` package is installed, without importing it."""
    return importlib.util.find_spec("ruff") is not None


def ruff_formatter(text: str, path: Path | None) -> str:
    """
    The formatter of ``formatter = "ruff"``: ``text`` with its imports sorted,
    as ruff's isort rule (I001) fixes them, then formatted by ``ruff format``.
    An import that a fix adds goes to its place among the others (#140).
    """
    return ruff_format(ruff_sort_imports(text, path), path)


def ruff_sort_imports(text: str, path: Path | None) -> str:
    """``text`` with its imports sorted by ``ruff check --select I --fix``."""
    return _ruff(["check", "--quiet", "--select", "I", "--fix"], text, path)


def ruff_format(text: str, path: Path | None) -> str:
    """``text`` formatted by ``ruff format``, with the settings for ``path``."""
    return _ruff(["format"], text, path)


def _ruff(arguments: Sequence[str], text: str, path: Path | None) -> str:
    """The output of ruff with ``arguments``, for ``text`` at ``path``."""
    from ruff.__main__ import find_ruff_bin

    filename = str(Path(path).resolve()) if path is not None else "<stdin>.py"
    command = [find_ruff_bin(), *arguments, "--stdin-filename", filename, "-"]
    # The ruff of tukuroi, with arguments of its own and no shell: the text goes
    # to its input (#130).
    result = subprocess.run(  # noqa: S603
        command, input=text.encode(), capture_output=True, check=False
    )
    if result.returncode:
        raise FormatError(result.stderr.decode(errors="replace").strip())
    return result.stdout.decode()
