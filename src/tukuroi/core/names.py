# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Qualified names from the imports of a module: after ``import typing as t``,
``t.Callable`` is ``typing.Callable``.

The names follow the scopes of Python, as :mod:`symtable` gives them (#146): an
import in a function or a class binds its name in that scope only, and a
parameter, an assignment or a ``global`` statement decides what a name of a
function is, as Python does. The targets of a comprehension hide the names
they bind. Within a scope, the order of the imports and the uses, and a name
assigned again after its import, are not followed: an import anywhere in a
scope binds its name in all of it. A name imported more than once in a scope
maps to each of the qualified names.

A text that ``symtable`` does not take, though :mod:`ast` parses it (such as
``nonlocal`` at the level of the module), gets one table for the whole module:
an import anywhere binds its name everywhere.
"""

import ast
import symtable
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from .source import Source

_EMPTY: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ImportTable:
    """
    The qualified names that the imports of a module bind: ``bindings``, those
    of the module scope, and the name of each node of the tree, by its scope.
    """

    bindings: Mapping[str, frozenset[str]]
    _resolved: Mapping[int, frozenset[str]] = field(
        default=MappingProxyType({}), compare=False, repr=False
    )

    @classmethod
    def from_source(cls, source: Source) -> Self:
        """
        The table of the imports of ``source``. A star import binds nothing; a
        relative import keeps its dots (``.typing.Callable``).
        """
        try:
            top = symtable.symtable(source.text, "<source>", "exec")
        except SyntaxError:
            return cls.from_tree(source.tree)
        scopes = _Scopes(top)
        scopes.walk(source.tree, top, _EMPTY)
        resolved = {
            id(node): scopes.resolve(node, table, hidden)
            for node, table, hidden in scopes.uses
        }
        return cls(scopes.bindings(top), MappingProxyType(resolved))

    @classmethod
    def from_tree(cls, tree: ast.Module) -> Self:
        """
        One table for the whole module of ``tree``, without its scopes: an
        import anywhere binds its name everywhere.
        """
        found: defaultdict[str, set[str]] = defaultdict(set)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for name, qualified in _bound(node):
                    found[name].add(qualified)
        bindings = {name: frozenset(names) for name, names in found.items()}
        return cls(MappingProxyType(bindings))

    def qualified_names(self, node: ast.expr) -> frozenset[str]:
        """
        The qualified names of ``node``: a name, or attributes of a name. Any
        other node, and a name that no import binds in its scope, has none. A
        name that is not a node of the tree, such as one made by a rule, is
        taken as a name of the module scope.
        """
        if isinstance(node, ast.Name):
            found = self._resolved.get(id(node))
            if found is not None:
                return found
            return self.bindings.get(node.id, _EMPTY)
        if isinstance(node, ast.Attribute):
            bases = self.qualified_names(node.value)
            return frozenset(f"{base}.{node.attr}" for base in bases)
        return _EMPTY


def _bound(node: ast.Import | ast.ImportFrom) -> Iterator[tuple[str, str]]:
    """The names that ``node`` binds, with their qualified names."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.asname:
                yield alias.asname, alias.name
            else:
                # "import a.b.c" binds "a".
                top = alias.name.partition(".")[0]
                yield top, top
        return
    dots = "." * node.level
    module = f"{dots}{node.module}." if node.module else dots
    for alias in node.names:
        if alias.name != "*":
            yield alias.asname or alias.name, module + alias.name


class _Scopes:
    """
    The walk of a tree along the tables of :mod:`symtable`: the imports of
    each table, the parent of each table, and each name with its table and
    the names that comprehensions hide there.
    """

    def __init__(self, top: symtable.SymbolTable) -> None:
        self.top = top
        self.imports: defaultdict[int, defaultdict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.parents: dict[int, symtable.SymbolTable] = {}
        self.uses: list[tuple[ast.Name, symtable.SymbolTable, frozenset[str]]] = []
        # The children of each table not taken yet, by name and line.
        self._children: dict[
            int, dict[tuple[str, int], list[symtable.SymbolTable]]
        ] = {}

    def bindings(self, table: symtable.SymbolTable) -> Mapping[str, frozenset[str]]:
        found = self.imports[id(table)]
        return MappingProxyType({n: frozenset(q) for n, q in found.items()})

    def walk(
        self, node: ast.AST, table: symtable.SymbolTable, hidden: frozenset[str]
    ) -> None:
        """Walk ``node``, evaluated in ``table``, with ``hidden`` names."""
        match node:
            case ast.Name():
                self.uses.append((node, table, hidden))
            case ast.Import() | ast.ImportFrom():
                for name, qualified in _bound(node):
                    self.imports[id(table)][name].add(qualified)
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                self._function(node, table, hidden)
            case ast.ClassDef():
                self._class(node, table, hidden)
            case ast.Lambda():
                self._each(_defaults(node.args), table, hidden)
                inner = self._child(table, "lambda", node.lineno) or table
                self.walk(node.body, inner, _EMPTY)
            case ast.GeneratorExp():
                self._comprehension(node, table, hidden, "genexpr")
            case ast.ListComp() | ast.SetComp() | ast.DictComp():
                name = type(node).__name__.lower()
                self._comprehension(node, table, hidden, name)
            case _:
                self._each(ast.iter_child_nodes(node), table, hidden)

    def _each(
        self,
        nodes: Iterable[ast.AST],
        table: symtable.SymbolTable,
        hidden: frozenset[str],
    ) -> None:
        for child in nodes:
            self.walk(child, table, hidden)

    def _function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        table: symtable.SymbolTable,
        hidden: frozenset[str],
    ) -> None:
        # The decorators and the defaults are evaluated where the function is
        # defined; its annotations are taken as evaluated there too.
        self._each(node.decorator_list, table, hidden)
        self._each(_defaults(node.args), table, hidden)
        outer = self._type_parameters(node, table, hidden)
        self._each(_annotations(node), outer, hidden)
        inner = self._child(outer, node.name, node.lineno) or outer
        self._each(node.body, inner, _EMPTY)

    def _class(
        self, node: ast.ClassDef, table: symtable.SymbolTable, hidden: frozenset[str]
    ) -> None:
        self._each(node.decorator_list, table, hidden)
        outer = self._type_parameters(node, table, hidden)
        self._each(node.bases, outer, hidden)
        self._each(node.keywords, outer, hidden)
        inner = self._child(outer, node.name, node.lineno) or outer
        self._each(node.body, inner, _EMPTY)

    def _type_parameters(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        table: symtable.SymbolTable,
        hidden: frozenset[str],
    ) -> symtable.SymbolTable:
        """The table of the type parameters of ``node`` (PEP 695), or ``table``."""
        if not node.type_params:
            return table
        scope = self._child(table, node.name, node.lineno) or table
        self._each(node.type_params, scope, hidden)
        return scope

    def _comprehension(
        self,
        node: ast.GeneratorExp | ast.ListComp | ast.SetComp | ast.DictComp,
        table: symtable.SymbolTable,
        hidden: frozenset[str],
        name: str,
    ) -> None:
        # The first iterable is evaluated outside the comprehension.
        first, *rest = node.generators
        self.walk(first.iter, table, hidden)
        inner = self._child(table, name, node.lineno)
        targets = frozenset(
            n.id
            for generator in node.generators
            for n in ast.walk(generator.target)
            if isinstance(n, ast.Name)
        )
        if inner is None:
            # Inlined (PEP 709): its targets hide the names of the scope. In a
            # class, it still does not see the names of the class.
            inner, inside = table, hidden | targets
            while inner.get_type() == symtable.SymbolTableType.CLASS:
                inner = self.parents.get(id(inner), self.top)
        else:
            inside = _EMPTY
        for generator in node.generators:
            self.walk(generator.target, inner, inside)
            self._each(generator.ifs, inner, inside)
        for generator in rest:
            self.walk(generator.iter, inner, inside)
        if isinstance(node, ast.DictComp):
            self._each([node.key, node.value], inner, inside)
        else:
            self.walk(node.elt, inner, inside)

    def _child(
        self, table: symtable.SymbolTable, name: str, line: int
    ) -> symtable.SymbolTable | None:
        """
        The child of ``table`` for the scope ``name`` that starts on ``line``,
        the next one of them in their order, or ``None`` if there is none.
        """
        if id(table) not in self._children:
            children: dict[tuple[str, int], list[symtable.SymbolTable]] = {}
            for child in table.get_children():
                key = (child.get_name(), child.get_lineno())
                children.setdefault(key, []).append(child)
            self._children[id(table)] = children
        children = self._children[id(table)]
        # Python 3.15 names the tables of lambdas and comprehensions <lambda>,
        # <genexpr>; 3.14, lambda, genexpr.
        found = children.get((name, line)) or children.get((f"<{name}>", line))
        if not found:
            return None
        child = found.pop(0)
        self.parents[id(child)] = table
        return child

    def resolve(
        self, name: ast.Name, table: symtable.SymbolTable, hidden: frozenset[str]
    ) -> frozenset[str]:
        """The qualified names of ``name``, used in ``table``."""
        if name.id in hidden:
            return _EMPTY
        return self._lookup(name.id, table)

    def _lookup(self, name: str, table: symtable.SymbolTable) -> frozenset[str]:
        try:
            symbol = table.lookup(name)
        except KeyError:
            # Only in an annotation, or in a scope of its own: of the module.
            return self._of(self.top, name)
        if symbol.is_imported():
            return self._of(table, name)
        if table is self.top:
            return _EMPTY
        if symbol.is_free():
            return self._enclosing(name, table)
        if symbol.is_global():
            return self._of(self.top, name)
        return _EMPTY

    def _enclosing(self, name: str, table: symtable.SymbolTable) -> frozenset[str]:
        """
        The names of a free variable: those of the function that binds it.
        symtable passes it through the scopes between, as a free variable of
        each. A class does not bind a name for the functions in it.
        """
        parent = self.parents.get(id(table))
        while parent is not None:
            if parent.get_type() != symtable.SymbolTableType.CLASS:
                symbol = parent.lookup(name)
                if symbol.is_local():
                    return self._of(parent, name) if symbol.is_imported() else _EMPTY
            parent = self.parents.get(id(parent))
        raise AssertionError(f"a function around a free variable binds it: {name}")

    def _of(self, table: symtable.SymbolTable, name: str) -> frozenset[str]:
        return frozenset(self.imports[id(table)].get(name, ()))


def _defaults(arguments: ast.arguments) -> list[ast.expr]:
    """The default values of ``arguments``."""
    return [*arguments.defaults, *(d for d in arguments.kw_defaults if d is not None)]


def _annotations(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    """The annotations of the parameters and of the return of ``node``."""
    arguments = node.args
    every = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *(a for a in (arguments.vararg, arguments.kwarg) if a is not None),
    ]
    found = [a.annotation for a in every if a.annotation is not None]
    return found + ([node.returns] if node.returns is not None else [])
