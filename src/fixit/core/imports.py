# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
A helper for fixes that need an import: the name to use, and the edit that adds
the import when the module does not have it yet.

The import goes on a new line after the last import at the top of the module,
or else after its docstring, or else before its first statement. It is not
merged into an import there: ruff sorts and merges imports (I001). When the
name is bound to something else in the module, there is no clean way to import
it, and the fix should not be offered.
"""

import ast
import re
from dataclasses import dataclass

from .edits import Edit
from .names import ImportTable
from .source import Source
from .text import Position, Span

_LINE_END = re.compile(r"\r\n|\r|\n")


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
