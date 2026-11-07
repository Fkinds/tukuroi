# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The engine: run rules on a source, once over its tree (#21).

Each rule gets an instance for the source. The tree is walked once, parents
before children; at each node, every rule gets a call of each of its
``visit_`` methods for the class of the node and the classes it comes from,
the most specific first (``visit_If``, then ``visit_stmt``).

The reports come back sorted by position, then by rule. A comment can suppress
a report (:mod:`fixit.core.suppression`); a fix that would drop a comment in a
range it replaces is taken off its report (:func:`fixit.core.edits.drops_comments`).
An exception in a rule is not caught. The directives that do not fit the
grammar come back with the reports, for the caller to warn about them.

:func:`fix` applies the fixes round after round, as ruff does, and formats the
text with ``ruff format`` when the fixes changed it (#21).
"""

import ast
import dataclasses
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass

from .directives import InvalidDirective, parse_directives
from .edits import apply_fixes, drops_comments
from .format import ruff_format
from .names import ImportTable
from .rule import Report, Rule
from .source import Source
from .suppression import NodeComments, is_suppressed
from .text import Position

# The most rounds of fixes, as ruff has (#21).
MAX_ROUNDS = 100


@dataclass(frozen=True, slots=True)
class BadDirective:
    """A ``# lint-ignore`` or ``# lint-fixme`` that does not fit the grammar."""

    position: Position
    text: str


@dataclass(frozen=True, slots=True)
class LintResult:
    """The reports of the rules on a source, and the directives that are wrong."""

    reports: tuple[Report, ...]
    bad_directives: tuple[BadDirective, ...]


def lint(source: Source, rules: Sequence[type[Rule]]) -> LintResult:
    """Run ``rules`` on ``source``."""
    imports = ImportTable.from_tree(source.tree)
    instances = [rule(source, imports) for rule in rules]
    calls: dict[type[ast.AST], list[object]] = {}
    for node in _walk(source.tree):
        kind = type(node)
        if kind not in calls:
            calls[kind] = [
                getattr(instance, method)
                for instance in instances
                for cls in kind.__mro__
                if (method := instance.visits().get(cls)) is not None
            ]
        for call in calls[kind]:
            call(node)  # type: ignore[operator]
    reports = [report for instance in instances for report in instance.reports]
    if reports:
        comments = NodeComments(source)
        reports = [
            _without_dropping_comments(report, source)
            for report in reports
            if not is_suppressed(comments.of(report.node), report.rule)
        ]
    reports.sort(key=lambda r: (r.position, r.rule))
    return LintResult(tuple(reports), tuple(_bad_directives(source)))


def _walk(node: ast.AST) -> Iterator[ast.AST]:
    """``node`` and the nodes under it, each before the nodes under it."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(list(ast.iter_child_nodes(current))))


def _without_dropping_comments(report: Report, source: Source) -> Report:
    if report.edits and drops_comments(report.edits, source.comments):
        return dataclasses.replace(report, edits=())
    return report


def _bad_directives(source: Source) -> Iterator[BadDirective]:
    for comment in source.comments:
        for directive in parse_directives(comment.text):
            if isinstance(directive, InvalidDirective):
                position = source.lines.position(comment.span.start)
                yield BadDirective(position, directive.text)


@dataclass(frozen=True, slots=True)
class FixResult:
    """
    The text after the fixes, the reports that the source had (those of the
    first round), how many fixes were applied in all the rounds, and whether the
    rounds ended before their limit.
    """

    text: str
    reports: tuple[Report, ...]
    applied: int
    converged: bool


def fix(
    source: Source,
    rules: Sequence[type[Rule]],
    *,
    choose: Callable[[Report], bool] | None = None,
    rounds: int = MAX_ROUNDS,
) -> FixResult:
    """
    Apply the fixes of ``rules`` to ``source``, round after round: in each round,
    lint, and apply the fixes by the start of their edits, then by rule, skipping
    those that overlap one applied before. Stop when no fix is left, or when the
    fixes no longer change the text. With ``choose``, apply only the fixes it
    takes, in one round. Format the text with ``ruff format`` if it changed.
    """
    first = lint(source, rules)
    text, applied, converged = source.text, 0, False
    result = first
    for round_ in range(1 if choose else rounds):
        if round_:
            result = lint(Source.from_text(text, source.path), rules)
        fixes = [r for r in result.reports if r.edits and (choose is None or choose(r))]
        fixes.sort(key=lambda r: (r.edits[0].span.start, r.rule))
        if not fixes:
            converged = True
            break
        done = apply_fixes(text, [r.edits for r in fixes])
        if done.text == text:
            converged = True
            break
        text, applied = done.text, applied + len(done.applied)
    else:
        converged = choose is not None
    if text != source.text:
        text = ruff_format(text, source.path)
    return FixResult(text, first.reports, applied, converged)
