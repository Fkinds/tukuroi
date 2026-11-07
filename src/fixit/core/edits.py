# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Edits of a text, and how the fixes made of them are applied.

A fix is the edits of one report: all of them are applied, or none. The new
engine replaces the ranges of the original text and leaves every other byte as
it is (#21). Fixes are applied in the order given; one that overlaps a fix
already applied is skipped, to be found again when the engine lints the result.
As ruff does, edits that only touch (one ends where the other starts) overlap
too, and so do two insertions at the same place.

A fix that would drop a comment inside a range it replaces is not offered at
all: the engine reports the violation without it (#21, issuecomment-6700667872).
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from .source import Comment
from .text import Span


@dataclass(frozen=True, slots=True)
class Edit:
    """Replace ``span`` with ``text``. An empty span inserts at its place."""

    span: Span
    text: str


@dataclass(frozen=True, slots=True)
class Applied:
    """The text after the fixes, and the indexes of the fixes applied."""

    text: str
    applied: tuple[int, ...]


def check_fix(edits: Sequence[Edit]) -> tuple[Edit, ...]:
    """
    The edits of one fix, by their place. Raises ``ValueError`` when two of them
    overlap: a fix cannot both replace and keep a character.
    """
    ordered = tuple(sorted(edits, key=lambda e: e.span))
    for before, after in pairwise(ordered):
        if after.span.start < before.span.end or before.span == after.span:
            raise ValueError(f"edits of a fix overlap: {before} and {after}")
    return ordered


def apply_fixes(text: str, fixes: Sequence[Sequence[Edit]]) -> Applied:
    """
    Apply ``fixes`` to ``text`` in their order, skipping each fix that overlaps
    (or touches) a fix applied before it.
    """
    taken: list[Span] = []
    chosen: list[Edit] = []
    applied: list[int] = []
    for index, fix in enumerate(fixes):
        edits = check_fix(fix)
        if any(_conflict(e.span, span) for e in edits for span in taken):
            continue
        for edit in edits:
            if edit.span.end > len(text):
                raise ValueError(f"edit out of the text: {edit}")
        taken.extend(e.span for e in edits)
        chosen.extend(edits)
        applied.append(index)
    parts: list[str] = []
    position = 0
    for edit in sorted(chosen, key=lambda e: e.span):
        parts.append(text[position : edit.span.start])
        parts.append(edit.text)
        position = edit.span.end
    parts.append(text[position:])
    return Applied("".join(parts), tuple(applied))


def drops_comments(edits: Sequence[Edit], comments: Sequence[Comment]) -> bool:
    """
    Whether the edits would drop a comment: a comment that a range meets must be
    inside it, and be in its new text as many times as the range holds it.
    """
    for edit in edits:
        inside: Counter[str] = Counter()
        for comment in comments:
            if not _meets(edit.span, comment.span):
                continue
            span = comment.span
            if span.start < edit.span.start or span.end > edit.span.end:
                return True
            inside[comment.text] += 1
        if any(edit.text.count(text) < count for text, count in inside.items()):
            return True
    return False


def _conflict(a: Span, b: Span) -> bool:
    """Whether two spans overlap or touch."""
    return a.start <= b.end and b.start <= a.end


def _meets(a: Span, b: Span) -> bool:
    """Whether two spans share a character."""
    return a.start < b.end and b.start < a.end
