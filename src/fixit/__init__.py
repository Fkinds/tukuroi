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
from .format import Formatter
from .ftypes import (
    CodePosition,
    CodeRange,
    Config,
    FileContent,
    LintViolation,
    Options,
    QualifiedRule,
    Result,
    Tags,
    Violation,
)

__all__ = [
    "CodePosition",
    "CodeRange",
    "Config",
    "Edit",
    "FileContent",
    "Formatter",
    "Invalid",
    "LintViolation",
    "Options",
    "Position",
    "QualifiedRule",
    "Range",
    "Result",
    "Rule",
    "Span",
    "Tags",
    "Valid",
    "Violation",
    "__version__",
    "fixit_bytes",
    "fixit_file",
    "fixit_paths",
    "print_result",
]
