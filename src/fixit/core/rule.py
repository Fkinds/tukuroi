# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The API to write a lint rule for the new engine (#21).

A rule is a subclass of :class:`Rule` with ``visit_<node>`` methods, named
after the classes of ``ast`` (``visit_Call``, or ``visit_stmt`` for every
statement). The engine makes an instance of each rule for each file, walks the
tree once, and calls the methods of every rule for each node. A method reports
a violation with :meth:`Rule.report`, with a fix or without one::

    class NoBadName(Rule):
        MESSAGE = "Use good, not bad."
        VALID = (Valid("good = 1\\n"),)
        INVALID = (Invalid("bad = 1\\n", expected_replacement="good = 1\\n"),)

        def visit_Name(self, node: ast.Name) -> None:
            if node.id == "bad":
                self.report(node, replacement="good")
"""

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import ClassVar

from .edits import Edit, check_fix
from .names import ImportTable
from .source import Source
from .text import Position, Span


@dataclass(frozen=True, slots=True)
class Valid:
    """Code that the rule does not report."""

    code: str


@dataclass(frozen=True, slots=True)
class Invalid:
    """
    Code that the rule reports. When given, the message, the code after the
    fix, and the position of the report are checked too.
    """

    code: str
    expected_message: str | None = None
    expected_replacement: str | None = None
    position: Position | None = None


@dataclass(frozen=True, slots=True)
class Report:
    """A violation: the rule, where, the message, and the edits of its fix."""

    rule: str
    span: Span
    position: Position
    message: str
    # Empty when the report has no fix.
    edits: tuple[Edit, ...]


class Rule:
    """
    A lint rule. ``MESSAGE`` is the message of a report that gives none; the
    name of the rule is the name of its class, without a "Rule" at its end.
    """

    MESSAGE: ClassVar[str] = ""
    VALID: ClassVar[Sequence[Valid | str]] = ()
    INVALID: ClassVar[Sequence[Invalid | str]] = ()

    _visits: ClassVar[Mapping[type[ast.AST], str]] = MappingProxyType({})

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        visits: dict[type[ast.AST], str] = {}
        for attribute in dir(cls):
            if not attribute.startswith("visit_"):
                continue
            node = getattr(ast, attribute.removeprefix("visit_"), None)
            if not (isinstance(node, type) and issubclass(node, ast.AST)):
                raise TypeError(f"{cls.__name__}.{attribute}: ast has no such node")
            visits[node] = attribute
        cls._visits = MappingProxyType(visits)

    def __init__(self, source: Source, imports: ImportTable) -> None:
        self.source = source
        self.imports = imports
        self.reports: list[Report] = []

    @classmethod
    def name(cls) -> str:
        """The name of the rule: the name of its class, without "Rule" at its end."""
        return cls.__name__.removesuffix("Rule")

    @classmethod
    def visits(cls) -> Mapping[type[ast.AST], str]:
        """The method to call for each class of node, by the class it visits."""
        return cls._visits

    def report(
        self,
        node: ast.AST,
        message: str | None = None,
        *,
        replacement: str | None = None,
        edits: Sequence[Edit] = (),
    ) -> None:
        """
        Report a violation at ``node``, with ``message`` or ``MESSAGE``. The fix,
        if any, is ``replacement`` for the text of ``node``, or ``edits``.
        """
        text = self.MESSAGE if message is None else message
        if not text:
            raise ValueError(f"{self.name()}: a report needs a message")
        if replacement is not None and edits:
            raise ValueError(f"{self.name()}: give replacement or edits, not both")
        span = self.source.span(node)
        fix = check_fix(edits) if replacement is None else (Edit(span, replacement),)
        position = self.source.lines.position(span.start)
        self.reports.append(Report(self.name(), span, position, text, fix))
