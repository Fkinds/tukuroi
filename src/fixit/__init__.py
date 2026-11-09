# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Linting framework built on ``ast``, with automatic fixes
"""

from .__version__ import __version__
from .api import fixit_bytes, fixit_file, fixit_paths, print_result
from .core.edits import Edit
from .core.rule import Invalid, Rule, Valid
from .core.text import Position, Range, Span
from .ftypes import (
    Config,
    Error,
    FileContent,
    Options,
    QualifiedRule,
    Result,
    Violation,
)

__all__ = [
    "Config",
    "Edit",
    "Error",
    "FileContent",
    "Invalid",
    "Options",
    "Position",
    "QualifiedRule",
    "Range",
    "Result",
    "Rule",
    "Span",
    "Valid",
    "Violation",
    "__version__",
    "fixit_bytes",
    "fixit_file",
    "fixit_paths",
    "print_result",
]
