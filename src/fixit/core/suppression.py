# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Which comments can suppress a violation reported at a node.

The new engine keeps where a ``# lint-ignore`` works as the libcst engine did
(the characterization tests of #21). libcst gives each comment to a node of
its tree; here the same comments are found from the ``ast`` tree and the
tokens. From the reported node, the walk goes up to the statement that holds
it, and takes:

- the comment at the end of the statement: after a simple statement, or after
  the ``:`` of the header of a compound statement (or after its one-line body);
- the comment lines above the statement (and its decorators), back to the code
  before it.

A statement in a one-line body (``if x: f()``) is not a statement of its own
for this: the walk goes on to the compound statement. Statements joined with
``;`` share the comment lines above the first of them. ``elif``, ``except`` and
``case`` stop the walk as statements do.
"""

import ast
import bisect
import tokenize
from collections.abc import Iterator, Sequence

from .directives import Directive, parse_directives
from .source import Comment, Source
from .text import Position

_NOT_CODE = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENDMARKER,
}

# The nodes that stop the walk, as the libcst nodes with leading lines do.
_CLAUSES = (ast.stmt, ast.excepthandler, ast.match_case)


def is_suppressed(comments: Sequence[Comment], rule: str) -> bool:
    """Whether a directive in ``comments`` suppresses ``rule``."""
    return any(
        isinstance(directive, Directive) and directive.covers(rule)
        for comment in comments
        for directive in parse_directives(comment.text)
    )


class NodeComments:
    """The comments that can suppress a violation at each node of a source."""

    def __init__(self, source: Source) -> None:
        self._source = source
        self._parents: dict[int, ast.AST] = {}
        for parent in ast.walk(source.tree):
            for child in ast.iter_child_nodes(parent):
                self._parents[id(child)] = parent
        lines = source.lines
        by_offset = {c.span.start: c for c in source.comments}
        # The lines that hold code (a part of a token that is not a comment).
        self._code_lines: set[int] = set()
        # The offset of each NEWLINE token, and the comment right before it.
        self._newlines: list[int] = []
        self._end_comments: list[Comment | None] = []
        previous: tokenize.TokenInfo | None = None
        for token in source.tokens:
            if token.type not in _NOT_CODE:
                self._code_lines.update(range(token.start[0], token.end[0] + 1))
            if token.type == tokenize.NEWLINE:
                self._newlines.append(lines.offset(Position(*token.start)))
                comment = None
                if previous is not None and previous.type == tokenize.COMMENT:
                    comment = by_offset[lines.offset(Position(*previous.start))]
                self._end_comments.append(comment)
            previous = token
        # The comment of each line that holds only a comment.
        self._line_comments: dict[int, Comment] = {}
        for comment in source.comments:
            line = lines.position(comment.span.start).line
            if line not in self._code_lines:
                self._line_comments[line] = comment

    def of(self, node: ast.AST) -> tuple[Comment, ...]:
        """The comments that can suppress a violation reported at ``node``."""
        found: list[Comment] = []
        current = node
        while not isinstance(current, ast.Module):
            if isinstance(current, _CLAUSES):
                found.extend(self._end_comment(current))
                first = self._first_on_line(current)
                if first is not None:
                    found.extend(self._leading(first))
                    return _sorted(found)
                # A one-line body: on to its compound statement.
            current = self._parent(current)
        found.extend(self._module_header())
        return _sorted(found)

    def _parent(self, node: ast.AST) -> ast.AST:
        return self._parents[id(node)]

    def _start(self, node: ast.AST) -> Position:
        if isinstance(node, ast.match_case):
            node = node.pattern
        return self._source.lines.position(self._source.span(node).start)

    def _line_text(self, line: int) -> str:
        """The text of ``line``, without its line end."""
        lines, text = self._source.lines, self._source.text
        start = end = lines.offset(Position(line, 0))
        while end < len(text) and text[end] not in "\r\n":
            end += 1
        return text[start:end]

    def _starts_line(self, node: ast.AST) -> bool:
        if isinstance(node, ast.match_case):
            return True  # "case" starts the line; its pattern does not.
        start = self._start(node)
        return not self._line_text(start.line)[: start.column].strip()

    def _first_on_line(self, node: ast.AST) -> ast.AST | None:
        """
        The statement that starts the line of ``node``: ``node``, or the first
        of the statements joined to it with ``;``. ``None`` in a one-line body.
        """
        if self._starts_line(node):
            return node
        siblings = self._siblings(node)
        if siblings is None:
            return None
        index = _index(siblings, node)
        while index > 0 and _end_line(siblings[index - 1]) == _line(siblings[index]):
            index -= 1
            if self._starts_line(siblings[index]):
                return siblings[index]
        return None

    def _siblings(self, node: ast.AST) -> list[ast.AST] | None:
        """The list of statements or clauses that holds ``node``."""
        for _, value in ast.iter_fields(self._parent(node)):
            if isinstance(value, list) and any(item is node for item in value):
                return value
        return None

    def _end_comment(self, node: ast.AST) -> Iterator[Comment]:
        """
        The comment at the end of the line of ``node``: after a simple
        statement, or after the header of a compound statement.
        """
        span = self._source.span(
            node.pattern if isinstance(node, ast.match_case) else node
        )
        offset = span.start if _is_compound(node) else span.end
        index = bisect.bisect_left(self._newlines, offset)
        if index < len(self._newlines) and (comment := self._end_comments[index]):
            yield comment

    def _leading(self, node: ast.AST) -> Iterator[Comment]:
        """The comment lines above ``node`` (with its decorators), back to code."""
        decorators = getattr(node, "decorator_list", None) or []
        line = min(self._start(n).line for n in [*decorators, node]) - 1
        region: list[Comment] = []
        while line >= 1 and line not in self._code_lines:
            if line in self._line_comments:
                region.append(self._line_comments[line])
            line -= 1
        region.reverse()
        yield from region

    def _module_header(self) -> Iterator[Comment]:
        """The comment lines before the first statement of the module."""
        body = self._source.tree.body
        for line, comment in sorted(self._line_comments.items()):
            if not body or line < self._start(body[0]).line:
                yield comment


def _sorted(comments: list[Comment]) -> tuple[Comment, ...]:
    return tuple(sorted(set(comments), key=lambda c: c.span))


def _index(items: Sequence[ast.AST], node: ast.AST) -> int:
    return next(i for i, item in enumerate(items) if item is node)


def _line(node: ast.AST) -> int:
    return getattr(node, "lineno", 0)


def _end_line(node: ast.AST) -> int:
    return getattr(node, "end_lineno", 0) or 0


def _is_compound(node: ast.AST) -> bool:
    """Whether ``node`` has a header and a block, as ``if`` and ``except`` do."""
    if isinstance(node, ast.excepthandler | ast.match_case):
        return True
    return any(
        isinstance(value, list) and value and isinstance(value[0], _CLAUSES)
        for _, value in ast.iter_fields(node)
    )
