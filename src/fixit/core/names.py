# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Qualified names from the imports of a module: after ``import typing as t``,
``t.Callable`` is ``typing.Callable``.

The table is one for the whole module. An import anywhere, even inside a
function, binds its name everywhere; the order of imports and uses, and a name
assigned again after its import, are not followed. A name imported more than
once maps to each of the qualified names.
"""

import ast
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Self


@dataclass(frozen=True, slots=True)
class ImportTable:
    """The qualified names that the imports of a module bind to each name."""

    bindings: Mapping[str, frozenset[str]]

    @classmethod
    def from_tree(cls, tree: ast.Module) -> Self:
        """
        The table of the imports in ``tree``. A star import binds nothing; a
        relative import keeps its dots (``.typing.Callable``).
        """
        found: defaultdict[str, set[str]] = defaultdict(set)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        found[alias.asname].add(alias.name)
                    else:
                        # "import a.b.c" binds "a".
                        top = alias.name.partition(".")[0]
                        found[top].add(top)
            elif isinstance(node, ast.ImportFrom):
                dots = "." * node.level
                module = f"{dots}{node.module}." if node.module else dots
                for alias in node.names:
                    if alias.name != "*":
                        found[alias.asname or alias.name].add(module + alias.name)
        bindings = {name: frozenset(names) for name, names in found.items()}
        return cls(MappingProxyType(bindings))

    def qualified_names(self, node: ast.expr) -> frozenset[str]:
        """
        The qualified names of ``node``: a name, or attributes of a name. Any
        other node, and a name that no import binds, has none.
        """
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id, frozenset())
        if isinstance(node, ast.Attribute):
            bases = self.qualified_names(node.value)
            return frozenset(f"{base}.{node.attr}" for base in bases)
        return frozenset()
