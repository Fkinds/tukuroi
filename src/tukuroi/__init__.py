# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Linting framework built on ``ast``, with automatic fixes
"""

from .__version__ import __version__
from .api import print_result, tukuroi_bytes, tukuroi_file, tukuroi_paths
from .core.edits import Edit
from .core.format import FormatterPlugin
from .core.names import ImportTable
from .core.rule import Invalid, Rule, Valid
from .core.source import Comment, Source, Token
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
from .output import OutputFormatPlugin

__all__ = [
    "Comment",
    "Config",
    "Edit",
    "Error",
    "FileContent",
    "FormatterPlugin",
    "ImportTable",
    "Invalid",
    "Options",
    "OutputFormatPlugin",
    "Position",
    "QualifiedRule",
    "Range",
    "Result",
    "Rule",
    "Source",
    "Span",
    "Token",
    "Valid",
    "Violation",
    "__version__",
    "print_result",
    "tukuroi_bytes",
    "tukuroi_file",
    "tukuroi_paths",
]
