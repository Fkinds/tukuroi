# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
``ruff format`` for the files that the new engine fixes (#21).

It runs the ``ruff`` executable of the ``ruff`` package, on the text through
stdin, with ``--stdin-filename``: the settings of ruff for that path (such as
the line length) apply.
"""

import subprocess
from pathlib import Path

from ruff.__main__ import find_ruff_bin


class FormatError(Exception):
    """``ruff format`` failed, for example on a syntax error."""


def ruff_format(text: str, path: Path | None) -> str:
    """``text`` formatted by ``ruff format``, with the settings for ``path``."""
    filename = str(Path(path).resolve()) if path is not None else "<stdin>.py"
    command = [find_ruff_bin(), "format", "--stdin-filename", filename, "-"]
    result = subprocess.run(
        command, input=text.encode(), capture_output=True, check=False
    )
    if result.returncode:
        raise FormatError(result.stderr.decode(errors="replace").strip())
    return result.stdout.decode()
