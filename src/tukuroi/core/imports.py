# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Helpers for fixes that need an import, or leave one unused: the name to use,
and the edit that adds the import when the module does not have it yet; and
the edits that take out the imports that no code reads any more (#141).

The import goes on a new line after the last import at the top of the module,
or else after its docstring, or else before its first statement. It is not
merged into an import there: with ``formatter = "ruff"``, ruff sorts and merges
the imports (I001, #140); without it, the import stays where it goes. When the
name is bound to something else in the module, there is no clean way to import
it, and the fix should not be offered.
"""

import ast
import re
import tokenize
from collections import defaultdict
from dataclasses import dataclass

from .edits import Edit, drops_comments
from .names import ImportTable, bound
from .source import Source
from .text import Position, Span

_LINE_END = re.compile(r"\r\n|\r|\n")
_WORD = re.compile(r"\w+")
# The tokens of the text of strings, where a name may be read: an annotation
# in quotes, or the names of __all__.
_STRINGS = {tokenize.STRING, tokenize.FSTRING_MIDDLE, tokenize.TSTRING_MIDDLE}


@dataclass(frozen=True, slots=True)
class Import:
    """The name to use in the code, and the edit that imports it, if needed."""

    name: str
    edit: Edit | None


def add_import(
    source: Source, imports: ImportTable, module: str, name: str | None = None
) -> Import | None:
    """
    Make ``module.name`` (``from module import name``), or ``module`` when
    ``name`` is ``None`` (``import module``), usable in ``source``. ``None``
    when the name it would bind is bound to something else.
    """
    wanted = f"{module}.{name}" if name else module
    for local, qualified in sorted(imports.bindings.items()):
        if wanted in qualified:
            return Import(local, None)
        if name and module in qualified:
            return Import(f"{local}.{name}", None)
    local = name or module.partition(".")[0]
    # "import a.b" binds "a" as "import a.c" does: that is no clash.
    same = set() if name else {local}
    if imports.bindings.get(local, same) - same or local in _defined(source.tree):
        return None
    if name:
        statement = f"from {module} import {name}"
    else:
        statement = f"import {module}"
    return Import(name or module, _insert(source, statement))


def _defined(tree: ast.Module) -> set[str]:
    """The names that the statements at the top of ``tree`` define."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        targets = getattr(node, "targets", None) or [getattr(node, "target", None)]
        for target in targets:
            for child in ast.walk(target) if target is not None else ():
                if isinstance(child, ast.Name):
                    names.add(child.id)
    return names


def _insert(source: Source, statement: str) -> Edit:
    """The edit that adds ``statement`` as a line of its own."""
    text, body = source.text, source.tree.body
    match = _LINE_END.search(text)
    newline = match.group() if match else "\n"
    # The docstring, then the imports at the top.
    after = 1 if body and _is_docstring(body[0]) else 0
    while after < len(body) and isinstance(body[after], ast.Import | ast.ImportFrom):
        after += 1
    if after:
        line = source.lines.position(source.span(body[after - 1]).end).line
        try:
            offset = source.lines.offset(Position(line + 1, 0))
        except ValueError:
            # It ends the text, without a line end.
            return Edit(Span(len(text), len(text)), newline + statement + newline)
        return Edit(Span(offset, offset), statement + newline)
    if body:
        # Before the first statement (and its decorators), after the comments.
        first = body[0]
        nodes = [*(getattr(first, "decorator_list", None) or []), first]
        line = min(source.lines.position(source.span(n).start).line for n in nodes)
        offset = source.lines.offset(Position(line, 0))
        return Edit(Span(offset, offset), statement + newline)
    # No statement at all: at the end.
    prefix = newline if text and not text.endswith(("\n", "\r")) else ""
    return Edit(Span(len(text), len(text)), prefix + statement + newline)


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def remove_import(source: Source, *names: str) -> tuple[Edit, ...]:
    """
    The edits that take out of ``source`` the imports of ``names``, qualified
    names that fixes may leave unused (#141): an import that binds one of them,
    such as ``from typing import NamedTuple`` for ``typing.NamedTuple``, and the
    import of a module that it is read through, such as ``import typing``.

    An import goes out only when no other place reads its name: no name of the
    code, and no word in a string (an annotation in quotes, ``__all__``). The
    name goes out of its statement with its comma, or, when no other name of
    the statement stays, the whole statement with its line. A statement that
    shares a line, the only statement of a block, and a range with a comment
    in it stay as they are.
    """
    if not names:
        return ()
    read = _reads(source)
    alone = _alone_in_a_block(source.tree)
    edits: list[Edit] = []
    for node in ast.walk(source.tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        span = source.span(node)
        bindings = list(bound(node))
        aliases = [a for a in node.names if a.name != "*"]
        unused = [
            alias
            for alias, (local, qualified) in zip(aliases, bindings, strict=True)
            if _imports_one_of(qualified, names)
            and all(span.start <= at < span.end for at in read[local])
        ]
        if not unused:
            continue
        if len(unused) == len(node.names):
            found = _without_statement(source, node, alone)
        else:
            found = _without_names(source, node.names, unused)
        if found and not drops_comments(found, source.comments):
            edits.extend(found)
    return tuple(edits)


def _imports_one_of(qualified: str, names: tuple[str, ...]) -> bool:
    """Whether ``qualified`` is one of ``names``, or a module they are in."""
    return any(n == qualified or n.startswith(f"{qualified}.") for n in names)


def _reads(source: Source) -> defaultdict[str, list[int]]:
    """Where each name is in the tokens: names, and words in strings."""
    found: defaultdict[str, list[int]] = defaultdict(list)
    for token in source.tokens:
        if token.type == tokenize.NAME:
            found[token.string].append(token.span.start)
        elif token.type in _STRINGS:
            for word in _WORD.finditer(token.string):
                found[word.group()].append(token.span.start + word.start())
    return found


def _alone_in_a_block(tree: ast.Module) -> set[int]:
    """The statements that are the only one of a block (not of the module)."""
    alone: set[int] = set()
    for node in ast.walk(tree):
        for name in ("body", "orelse", "finalbody"):
            block = getattr(node, name, None)
            if node is not tree and isinstance(block, list) and len(block) == 1:
                alone.add(id(block[0]))
    return alone


def _without_statement(
    source: Source, node: ast.Import | ast.ImportFrom, alone: set[int]
) -> list[Edit]:
    """The edit that takes out ``node`` with its lines, if they are its own."""
    if id(node) in alone:
        return []
    span = source.span(node)
    start = source.lines.position(span.start)
    line_start = source.lines.offset(Position(start.line, 0))
    end = source.lines.position(span.end)
    try:
        next_line = source.lines.offset(Position(end.line + 1, 0))
    except ValueError:
        next_line = len(source.text)
    before = source.text[line_start : span.start]
    after = source.text[span.end : next_line]
    if before.strip() or after.strip():
        return []
    return [Edit(Span(line_start, next_line), "")]


def _without_names(
    source: Source, aliases: list[ast.alias], unused: list[ast.alias]
) -> list[Edit]:
    """
    The edits that take ``unused`` out of ``aliases``, some of them: each run of
    them up to the next name that stays, or, at the end, from the name before.
    """
    edits: list[Edit] = []
    index = 0
    while index < len(aliases):
        if not any(aliases[index] is a for a in unused):
            index += 1
            continue
        last = index
        while last + 1 < len(aliases) and any(aliases[last + 1] is a for a in unused):
            last += 1
        if last + 1 < len(aliases):
            start = source.span(aliases[index]).start
            end = source.span(aliases[last + 1]).start
        else:
            start = source.span(aliases[index - 1]).end
            end = source.span(aliases[last]).end
        edits.append(Edit(Span(start, end), ""))
        index = last + 1
    return edits
