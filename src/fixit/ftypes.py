# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import re
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    TypedDict,
    TypeVar,
)

from libcst import CSTNode, CSTNodeT, FlattenSentinel, RemovalSentinel
from libcst._add_slots import add_slots
from libcst.metadata import CodePosition as CodePosition  # noqa: PLC0414  # re-export
from libcst.metadata import CodeRange as CodeRange  # noqa: PLC0414  # re-export

from .core.text import Range

T = TypeVar("T")

STDIN = Path("-")

# Re-export libcst's position types. #21 replaces them.
CodeRange  # noqa: B018
CodePosition  # noqa: B018

FileContent = bytes

NodeReplacement = CSTNodeT | FlattenSentinel[CSTNodeT] | RemovalSentinel

Metrics = dict[str, Any]
MetricsHook = Callable[[Metrics], None]

VisitorMethod = Callable[[CSTNode], None]
VisitHook = Callable[[str], AbstractContextManager[None]]


class OutputFormat(str, Enum):
    custom = "custom"
    fixit = "fixit"
    # json = "json"  # TODO
    vscode = "vscode"


LintIgnoreRegex = re.compile(
    r"""
    \#\s*                   # leading hash and whitespace
    (lint-(?:ignore|fixme)) # directive
    (?:
        (?::\s*|\s+)        # separator
        (
            \w+             # first rule name
            (?:,\s*\w+)*    # subsequent rule names
        )
    )?                      # rule names are optional
    """,
    re.VERBOSE,
)


QualifiedRuleRegex = re.compile(
    r"""
    ^
    (?P<module>
        (?P<local>\.)?
        [a-zA-Z0-9_]+(\.[a-zA-Z0-9_-]+)*
    )
    (?::(?P<name>[a-zA-Z0-9_-]+))?
    $
    """,
    re.VERBOSE,
)


class QualifiedRuleRegexResult(TypedDict):
    module: str
    name: str | None
    local: str | None


def is_sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def is_collection(value: Any) -> bool:
    return isinstance(value, Iterable) and not isinstance(value, (str, bytes))


# The packages of the rules that come with Fixit. With custom rules turned off
# (`--no-custom-rules`), Fixit imports no other rules.
BUILTIN_RULE_PACKAGES = ("fixit.rules",)


@dataclass(frozen=True)
class QualifiedRule:
    module: str
    name: str | None = None
    local: str | None = None
    # Part of the name of a local rule (#21): ".rules" of two configs differ.
    root: Path | None = field(default=None, hash=False)

    @property
    def builtin(self) -> bool:
        """
        Whether this names rules that come with Fixit, not custom rules. The
        module of a local rule starts with ".", so it never matches.
        """
        return any(
            self.module == package or self.module.startswith(f"{package}.")
            for package in BUILTIN_RULE_PACKAGES
        )

    def __str__(self) -> str:
        return self.module + (f":{self.name}" if self.name else "")

    def __lt__(self, other: object) -> bool:
        if isinstance(other, QualifiedRule):
            return str(self) < str(other)
        return NotImplemented


@dataclass
class Options:
    """
    Command-line options to affect runtime behavior
    """

    debug: bool | None = None
    config_file: Path | None = None
    rules: Sequence[QualifiedRule] = ()
    output_format: OutputFormat | None = None
    output_template: str = ""
    print_metrics: bool = False
    # False: import only the built-in rules (see BUILTIN_RULE_PACKAGES).
    custom_rules: bool = True


@dataclass
class LSPOptions:
    """
    Command-line options to affect LSP runtime behavior
    """

    tcp: int | None
    ws: int | None
    stdio: bool = True
    debounce_interval: float = 0.5


@dataclass
class Config:
    """
    Materialized configuration valid for processing a single file.
    """

    path: Path = field(default_factory=Path)
    root: Path = field(default_factory=Path.cwd)

    # feature flags
    enable_root_import: bool | Path = False
    # False: import only the built-in rules, and ignore enable_root_import.
    custom_rules: bool = True

    # rule selection
    enable: list[QualifiedRule] = field(
        default_factory=lambda: [QualifiedRule("fixit.rules")]
    )
    disable: list[QualifiedRule] = field(default_factory=list)

    # output formatting options
    output_format: OutputFormat = OutputFormat.fixit
    output_template: str = ""

    def __post_init__(self) -> None:
        self.path = self.path.resolve()
        self.root = self.root.resolve()


@dataclass
class RawConfig:
    path: Path
    data: dict[str, Any]

    def __post_init__(self) -> None:
        self.path = self.path.resolve()


@add_slots
@dataclass(frozen=True)
class LintViolation:
    """
    An individual lint error, with an optional replacement and expected diff.
    """

    rule_name: str
    range: CodeRange
    message: str
    node: CSTNode
    replacement: NodeReplacement[CSTNode] | None
    diff: str = ""

    @property
    def autofixable(self) -> bool:
        """
        Whether the violation includes a suggested replacement.
        """
        return bool(self.replacement)


@dataclass(frozen=True, slots=True)
class Violation:
    """
    A violation that the new engine (#21) reports: the rule, where it is (lines
    from 1, columns in characters from 0), the message, whether the engine can
    fix it, and the diff of its fix alone.
    """

    rule_name: str
    range: Range
    message: str
    autofixable: bool
    diff: str = ""


@dataclass
class Result:
    """
    A single lint result for a given file and lint rule. A file whose fixes
    were applied ends with a result that has only ``applied``: how many.
    """

    path: Path
    violation: LintViolation | Violation | None
    error: tuple[Exception, str] | None = None
    applied: int = 0
