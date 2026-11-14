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
a report (:mod:`tukuroi.core.suppression`); a fix that would drop a comment in a
range it replaces is taken off its report (:func:`tukuroi.core.edits.drops_comments`).
An exception in a rule is not caught. The directives that do not fit the
grammar come back with the reports, for the caller to warn about them.

:func:`fix` applies the fixes round after round, as ruff does. With a formatter
(``ruff format``, when a config chooses it), it formats the text that the fixes
changed (#21, #108).
"""

import ast
import dataclasses
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from .directives import InvalidDirective, parse_directives
from .edits import apply_fixes, drops_comments
from .imports import remove_import
from .names import ImportTable
from .rule import Report, Rule
from .source import ParseError, Source
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
    imports = ImportTable.from_source(source)
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
    first round), how many fixes were applied in all the rounds, whether the
    rounds ended before their limit, and the reports whose fixes would break the
    code, which are not applied (#147).
    """

    text: str
    reports: tuple[Report, ...]
    applied: int
    converged: bool
    broken: tuple[Report, ...] = ()


def fix(
    source: Source,
    rules: Sequence[type[Rule]],
    *,
    choose: Callable[[Report], bool] | None = None,
    rounds: int = MAX_ROUNDS,
    formatter: Callable[[str, Path | None], str] | None = None,
) -> FixResult:
    """
    Apply the fixes of ``rules`` to ``source``, round after round: in each round,
    lint, and apply the fixes by the start of their edits, then by rule, skipping
    those that overlap one applied before. Stop when no fix is left, or when the
    fixes no longer change the text. With ``choose``, apply only the fixes it
    takes, in one round. Format the text with ``formatter`` if one is given and
    the text changed (#108).

    A fix that would break the code, so that the text no longer parses, is not
    applied, nor tried again in the rounds after (#147): the others are.
    """
    first = lint(source, rules)
    text, applied, converged = source.text, 0, False
    result = first
    broken: dict[tuple[str, tuple[str, ...]], Report] = {}
    # The qualified names that the applied fixes may leave unused (#141).
    unused: set[str] = set()
    for round_ in range(1 if choose else rounds):
        if round_:
            result = lint(Source.from_text(text, source.path), rules)
        fixes = [
            r
            for r in result.reports
            if r.edits and (choose is None or choose(r)) and _fix_key(r) not in broken
        ]
        fixes.sort(key=lambda r: (r.edits[0].span.start, r.rule))
        if not fixes:
            converged = True
            break
        done, taken, failed = _apply(text, fixes, source.path)
        broken.update((_fix_key(r), r) for r in failed)
        if done == text:
            converged = True
            break
        text, applied = done, applied + len(taken)
        unused.update(name for r in taken for name in r.unused_imports)
    else:
        converged = choose is not None
    if unused:
        text = _without_imports(text, source.path, unused)
    if formatter is not None and text != source.text:
        text = formatter(text, source.path)
    return FixResult(text, first.reports, applied, converged, tuple(broken.values()))


def _fix_key(report: Report) -> tuple[str, tuple[str, ...]]:
    """A fix, wherever it is: its rule and the texts of its edits."""
    return report.rule, tuple(edit.text for edit in report.edits)


def _apply(
    text: str, fixes: Sequence[Report], path: Path | None
) -> tuple[str, list[Report], list[Report]]:
    """
    Apply ``fixes`` to ``text``, as :func:`apply_fixes` does: the text, the
    fixes applied, and those left out. If the result does not parse, apply
    them one at a time, in their order, and leave out each that the text does
    not parse after (#147).
    """
    done = apply_fixes(text, [r.edits for r in fixes])
    if _parses(done.text, path):
        return done.text, [fixes[i] for i in done.applied], []
    kept: list[Report] = []
    failed: list[Report] = []
    for report in fixes:
        trial = apply_fixes(text, [r.edits for r in [*kept, report]])
        if len(trial.applied) == len(kept):
            # It overlaps one kept: tried in the next round.
            continue
        if _parses(trial.text, path):
            kept.append(report)
        else:
            failed.append(report)
    return apply_fixes(text, [r.edits for r in kept]).text, kept, failed


def _without_imports(text: str, path: Path | None, names: set[str]) -> str:
    """
    ``text`` without the imports of ``names`` that no code reads (#141), if it
    still parses without them.
    """
    edits = remove_import(Source.from_text(text, path), *sorted(names))
    if not edits:
        return text
    removed = apply_fixes(text, [edits]).text
    return removed if _parses(removed, path) else text


def _parses(text: str, path: Path | None) -> bool:
    try:
        Source.from_text(text, path)
    except ParseError:
        return False
    return True
