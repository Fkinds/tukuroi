# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The grammar of the ``# lint-ignore`` and ``# lint-fixme`` directives (#21,
issuecomment-6706326492, corrected in issuecomment-6706590667).

A comment is split at ``#``, and each part is read on its own, so that a
directive can follow the directive of another tool (``# noqa  # lint-ignore``).
A part that starts with ``lint-ignore`` or ``lint-fixme``, followed by no
letter, digit or ``_``, is a directive. Its forms are::

    lint-ignore
    lint-ignore: <name>, <name>

with any spaces around ``:`` and ``,``, and nothing after the names. A name is
a Python identifier, so a qualified name (``tukuroi.rules:X``) does not fit. A
directive that does not fit suppresses nothing; the engine warns about it.
"""

import re
from dataclasses import dataclass
from typing import Literal

_DIRECTIVE = re.compile(r"lint-(ignore|fixme)(?!\w)")


@dataclass(frozen=True, slots=True)
class Directive:
    """
    A directive that fits the grammar. ``names`` is ``None`` for one without
    names, which suppresses every rule.
    """

    kind: Literal["ignore", "fixme"]
    names: tuple[str, ...] | None

    def covers(self, rule: str) -> bool:
        """
        Whether this suppresses ``rule``, the name of a rule without a "Rule" at
        its end. A name in the directive matches with the same case, with or
        without one "Rule" at its end.
        """
        if self.names is None:
            return True
        return any(name.removesuffix("Rule") == rule for name in self.names)


@dataclass(frozen=True, slots=True)
class InvalidDirective:
    """A directive that does not fit the grammar: the text of its part."""

    text: str


def parse_directives(comment: str) -> tuple[Directive | InvalidDirective, ...]:
    """The directives in ``comment``, a comment from ``#`` to the end of a line."""
    found: list[Directive | InvalidDirective] = []
    for part in comment.split("#")[1:]:
        text = part.strip()
        match = _DIRECTIVE.match(text)
        if match is None:
            continue
        kind: Literal["ignore", "fixme"] = "ignore" if match[1] == "ignore" else "fixme"
        rest = text[match.end() :].strip()
        if not rest:
            found.append(Directive(kind, None))
            continue
        names = [name.strip() for name in rest.removeprefix(":").split(",")]
        if rest.startswith(":") and all(name.isidentifier() for name in names):
            found.append(Directive(kind, tuple(names)))
        else:
            found.append(InvalidDirective(text))
    return tuple(found)
