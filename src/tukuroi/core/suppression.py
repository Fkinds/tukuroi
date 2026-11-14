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
  before it. When the clause before it ends with an indented block, the comment
  lines up to the last one indented as deep as that block belong to the block,
  not to the statement (libcst's ``IndentedBlock.footer``).

On the way up, the walk also takes, as libcst does:

- after an item of a list of items with commas (an argument, a parameter, an
  element, an import, a ``with`` item), the comment after its comma;
- in a ``[...]`` (a list, a list comprehension, a subscript), the comment lines
  right after the ``[`` line, and the comment after the last item when ``]`` is
  on a later line;
- from a decorator, the comment at its end and the comment lines between it and
  the decorator before it; and at a decorated statement, the comment lines
  between its decorators and itself.

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
from .text import Position, Span

_NOT_CODE = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENDMARKER,
}

_LAYOUT = {
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
        # The tokens other than line ends and indents, with their offsets, and
        # the index of the matching bracket of each bracket.
        self._tokens = [t for t in source.tokens if t.type not in _LAYOUT]
        self._starts = [lines.offset(Position(*t.start)) for t in self._tokens]
        self._match: dict[int, int] = {}
        opened: list[int] = []
        for index, token in enumerate(self._tokens):
            if token.type == tokenize.OP and token.string in "([{":
                opened.append(index)
            elif token.type == tokenize.OP and token.string in ")]}" and opened:
                start = opened.pop()
                self._match[start] = index
                self._match[index] = start
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
            if isinstance(current, ast.List | ast.ListComp | ast.Subscript):
                found.extend(self._bracket_comments(current))
            if isinstance(current, _CLAUSES):
                found.extend(self._end_comment(current))
                first = self._first_on_line(current)
                if first is not None:
                    found.extend(self._after_decorators(current))
                    found.extend(self._leading(first))
                    return _sorted(found)
                # A one-line body: on to its compound statement.
            parent = self._parent(current)
            item = self._item(current, parent)
            if item is not None and self._owns_comma(current, parent):
                found.extend(self._comma_comment(item))
            decorators = getattr(parent, "decorator_list", None) or []
            if any(d is current for d in decorators):
                found.extend(self._decorator_comments(current, decorators))
            current = parent
        found.extend(self._module_header())
        return _sorted(found)

    def _item(self, node: ast.AST, parent: ast.AST) -> Span | None:
        """
        The span of the item that ``node`` is in a list of items with commas in
        ``parent``, if it is one: the argument, the parameter with its default,
        the element (a key with its value), the import, the ``with`` item.
        """
        span = self._source.span
        lists: list[list[ast.AST]] = []
        if isinstance(parent, ast.Call):
            lists = [parent.args, parent.keywords]
        elif isinstance(parent, ast.ClassDef):
            lists = [parent.bases, parent.keywords, parent.type_params]
        elif isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            lists = [parent.type_params]
        elif isinstance(parent, ast.List | ast.Tuple | ast.Set):
            lists = [parent.elts]
        elif isinstance(parent, ast.Import | ast.ImportFrom):
            lists = [parent.names]
        elif isinstance(parent, ast.Dict):
            for key, value in zip(parent.keys, parent.values, strict=True):
                if node is key or node is value:
                    return Span(span(key or value).start, span(value).end)
            raise AssertionError("a child of a dict is one of its keys or values")
        elif isinstance(parent, ast.arguments):
            return self._parameter(node, parent)
        elif isinstance(node, ast.withitem):
            end = node.optional_vars or node.context_expr
            return Span(span(node.context_expr).start, span(end).end)
        if any(item is node for items in lists for item in items):
            return span(node)
        return None

    def _owns_comma(self, node: ast.AST, parent: ast.AST) -> bool:
        """
        Whether the comma after ``node`` holds the comment after it: not for the
        last element of a list, set, dict or tuple, whose closing bracket holds
        it (libcst).
        """
        if isinstance(parent, ast.List | ast.Set | ast.Tuple):
            return parent.elts[-1] is not node
        if isinstance(parent, ast.Dict):
            return parent.keys[-1] is not node and parent.values[-1] is not node
        return True

    def _parameter(self, node: ast.AST, arguments: ast.arguments) -> Span:
        """The span of the parameter that ``node`` is, or is the default of."""
        span = self._source.span
        positional = [*arguments.posonlyargs, *arguments.args]
        defaults = [None] * (len(positional) - len(arguments.defaults))
        pairs = [
            *zip(positional, [*defaults, *arguments.defaults], strict=True),
            *zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True),
            *((a, None) for a in (arguments.vararg, arguments.kwarg) if a),
        ]
        for parameter, default in pairs:
            if node is parameter or node is default:
                return Span(span(parameter).start, span(default or parameter).end)
        raise AssertionError("a child of arguments is a parameter or a default")

    def _comma_comment(self, item: Span) -> Iterator[Comment]:
        """The comment right after the comma after ``item``, on the same line."""
        after = self._after(item)
        tokens = self._tokens
        if after + 1 < len(tokens) and tokens[after].string == ",":
            comment = tokens[after + 1]
            if (
                comment.type == tokenize.COMMENT
                and comment.start[0] == tokens[after].end[0]
            ):
                yield self._comment(after + 1)

    def _after(self, item: Span) -> int:
        """The index of the token after ``item``, and after the parentheses around it."""
        after = bisect.bisect_left(self._starts, item.end)
        first = bisect.bisect_left(self._starts, item.start)
        while (
            first > 0
            and self._tokens[first - 1].string == "("
            and self._match.get(first - 1) == after
        ):
            first, after = first - 1, after + 1
        return after

    def _bracket_comments(self, node: ast.AST) -> Iterator[Comment]:
        """
        In a ``[...]``: the comment lines after the line of ``[``, before the
        first item, and the comment after the last item (a comment runs to the end
        of its line, so ``]`` is on a later line).
        """
        span = self._source.span
        start = (
            span(node.value).end
            if isinstance(node, ast.Subscript)
            else span(node).start
        )
        opening = bisect.bisect_left(self._starts, start)
        while self._tokens[opening].string != "[":
            opening += 1
        closing = self._match[opening]
        tokens = self._tokens
        first = next(
            (
                i
                for i in range(opening + 1, closing)
                if tokens[i].type != tokenize.COMMENT
            ),
            closing,
        )
        first_line = tokens[first].start[0]
        for line in range(tokens[opening].start[0] + 1, first_line):
            if line in self._line_comments:
                yield self._line_comments[line]
        last = max(
            (i for i in range(opening, closing) if tokens[i].type != tokenize.COMMENT),
            default=opening,
        )
        comment = tokens[last + 1]
        if (
            last > opening
            and comment.type == tokenize.COMMENT
            and comment.start[0] == tokens[last].end[0]
        ):
            yield self._comment(last + 1)

    def _decorator_comments(
        self, decorator: ast.AST, decorators: Sequence[ast.AST]
    ) -> Iterator[Comment]:
        """The comment at the end of ``decorator``, and the lines above it."""
        index = _index(decorators, decorator)
        offset = self._source.span(decorator).end
        newline = bisect.bisect_left(self._newlines, offset)
        if newline < len(self._newlines) and (comment := self._end_comments[newline]):
            yield comment
        if index:
            yield from self._lines_between(
                decorators[index - 1], self._start(decorator).line
            )

    def _after_decorators(self, node: ast.AST) -> Iterator[Comment]:
        """The comment lines between the decorators of ``node`` and ``node``."""
        decorators = getattr(node, "decorator_list", None) or []
        if decorators:
            yield from self._lines_between(decorators[-1], self._start(node).line)

    def _lines_between(self, before: ast.AST, line: int) -> Iterator[Comment]:
        """The comment lines after the end of ``before`` and before ``line``."""
        end = self._source.lines.position(self._source.span(before).end).line
        for number in range(end + 1, line):
            if number in self._line_comments:
                yield self._line_comments[number]

    def _comment(self, index: int) -> Comment:
        start = self._starts[index]
        return next(c for c in self._source.comments if c.span.start == start)

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
        index = _index(siblings, node)
        while index > 0 and _end_line(siblings[index - 1]) == _line(siblings[index]):
            index -= 1
            if self._starts_line(siblings[index]):
                return siblings[index]
        return None

    def _siblings(self, node: ast.AST) -> list[ast.AST]:
        """The list of statements or clauses that holds ``node``, a clause."""
        for _, value in ast.iter_fields(self._parent(node)):
            if isinstance(value, list) and any(item is node for item in value):
                return value
        raise AssertionError("a clause is in a list of its parent")

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
        indent = self._closing_block_indent(node)
        if indent is not None:
            columns = [self._source.lines.position(c.span.start).column for c in region]
            last = max((i for i, c in enumerate(columns) if c >= indent), default=-1)
            region = region[last + 1 :]
        yield from region

    def _closing_block_indent(self, node: ast.AST) -> int | None:
        """
        The indent of the block that ends right before ``node``, when the clause
        before ``node`` ends with an indented block.
        """
        previous = self._previous_clause(node)
        block = self._last_block(previous) if previous is not None else []
        if not block or not self._starts_line(block[0]):
            return None
        line = self._line_text(self._start(block[0]).line)
        return len(line) - len(line.lstrip())

    def _previous_clause(self, node: ast.AST) -> ast.AST | list[ast.stmt] | None:
        """The clause, or the block, right before ``node``."""
        parent = self._parent(node)
        if isinstance(node, ast.If) and self._is_elif_of(node, parent):
            return parent.body  # type: ignore[attr-defined]
        if isinstance(node, ast.excepthandler) and isinstance(
            parent, ast.Try | ast.TryStar
        ):
            index = _index(parent.handlers, node)
            return parent.handlers[index - 1] if index else parent.body
        if isinstance(node, ast.match_case) and isinstance(parent, ast.Match):
            index = _index(parent.cases, node)
            return parent.cases[index - 1] if index else None
        siblings = self._siblings(node)
        index = _index(siblings, node)
        return siblings[index - 1] if index else None

    def _is_elif_of(self, node: ast.If, parent: ast.AST) -> bool:
        """Whether ``node`` is the ``elif`` of ``parent``, not an ``if`` in an ``else``."""
        if not (
            isinstance(parent, ast.If) and parent.orelse and parent.orelse[0] is node
        ):
            return False
        start = self._start(node)
        return self._line_text(start.line)[start.column :].startswith("elif")

    def _last_block(self, clause: ast.AST | list[ast.stmt]) -> Sequence[ast.AST]:
        """The statements of the block that ``clause`` ends with."""
        if isinstance(clause, list):
            return clause
        if isinstance(clause, ast.If):
            orelse = clause.orelse
            if orelse and self._is_elif_of(orelse[0], clause):
                return self._last_block(orelse[0])
            return orelse or clause.body
        if isinstance(clause, ast.For | ast.AsyncFor | ast.While):
            return clause.orelse or clause.body
        if isinstance(clause, ast.Try | ast.TryStar):
            if clause.finalbody or clause.orelse:
                return clause.finalbody or clause.orelse
            return clause.handlers[-1].body if clause.handlers else clause.body
        if isinstance(clause, ast.Match):
            return clause.cases  # The block of the cases, not of the last case.
        body = getattr(clause, "body", None)
        return body if isinstance(body, list) else []

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
