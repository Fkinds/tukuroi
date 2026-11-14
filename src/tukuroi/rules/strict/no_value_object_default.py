# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast

from ...core.rule import Invalid, Rule, Valid
from ...core.text import Position

_DATACLASS = "dataclasses.dataclass"
_FIELD = "dataclasses.field"
_CLASSVARS = {"typing.ClassVar", "typing_extensions.ClassVar"}


class NoValueObjectDefault(Rule):
    """
    A value object takes every value of its fields from its caller: no field
    has a default, which the caller would get without writing it. Explicit is
    better than implicit.

    A value object is a class of ``@dataclass(frozen=True)`` without
    ``eq=False``. A frozen dataclass with ``eq=False`` is an entity, equal to
    the objects of its identity only, and may give its ``id`` a default. The
    fields that the caller does not pass keep theirs: ``field(init=False)``,
    and the ``ClassVar`` annotations, which are not fields.
    """

    MESSAGE = (
        "A field of a value object takes no default: the caller passes every value."
    )

    VALID = (
        Valid(
            """
            from dataclasses import dataclass

            @dataclass(frozen=True, kw_only=True)
            class Money:
                amount: int
                currency: str
            """
        ),
        # An entity: equal by its id.
        Valid(
            """
            import uuid
            from dataclasses import dataclass, field

            @dataclass(frozen=True, kw_only=True, eq=False)
            class Order:
                id: uuid.UUID = field(default_factory=uuid.uuid4)
            """
        ),
        Valid(
            """
            from dataclasses import dataclass

            @dataclass
            class Options:
                debug: bool = False
            """
        ),
        Valid(
            """
            from dataclasses import dataclass

            @dataclass(frozen=False)
            class Options:
                debug: bool = False
            """
        ),
        Valid(
            """
            import typing
            from dataclasses import KW_ONLY, dataclass, field
            from typing import ClassVar

            @dataclass(frozen=True)
            class Money:
                CURRENCIES: ClassVar[frozenset[str]] = frozenset({"JPY"})
                LIMIT: typing.ClassVar = 100
                amount: int
                _: KW_ONLY
                cents: int = field(init=False, default=0)
                note: str = field(repr=False)
            """
        ),
        # Only a literal frozen=True makes a value object.
        Valid(
            """
            from dataclasses import dataclass

            FROZEN = True

            @dataclass(frozen=FROZEN)
            class Money:
                amount: int = 0
            """
        ),
        # A dataclass of another library, with the same name.
        Valid(
            """
            from pydantic.dataclasses import dataclass

            @dataclass(frozen=True)
            class Money:
                amount: int = 0
            """
        ),
        Valid(
            """
            class Money:
                amount: int = 0
            """
        ),
    )

    INVALID = (
        Invalid(
            """
            from dataclasses import dataclass

            @dataclass(frozen=True, kw_only=True)
            class Money:
                amount: int
                currency: str = "JPY"
            """,
            position=Position(6, 20),
        ),
        Invalid(
            """
            from dataclasses import dataclass, field

            @dataclass(frozen=True, eq=True)
            class Money:
                amount: int = field(init=True, default=0)
            """,
            position=Position(5, 43),
        ),
        Invalid(
            """
            import dataclasses

            @dataclasses.dataclass(frozen=True)
            class Basket:
                items: list[str] = dataclasses.field(default_factory=list)
            """,
            position=Position(5, 57),
        ),
        Invalid(
            """
            from dataclasses import InitVar, dataclass as dc, field as f
            from typing import final

            @final
            @dc(frozen=True)
            class Money:
                amount: int = f(default=0)
                rate: InitVar[int] = 1
            """,
        ),
    )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if not any(self._value_object(decorator) for decorator in node.decorator_list):
            return
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and statement.value is not None:
                default = self._default(statement.annotation, statement.value)
                if default is not None:
                    self.report(default)

    def _value_object(self, decorator: ast.expr) -> bool:
        """Whether ``decorator`` is ``@dataclass(frozen=True)``, without ``eq=False``."""
        if not (
            isinstance(decorator, ast.Call)
            and _DATACLASS in self.imports.qualified_names(decorator.func)
        ):
            return False
        flags = {
            keyword.arg: keyword.value.value
            for keyword in decorator.keywords
            if isinstance(keyword.value, ast.Constant)
        }
        return flags.get("frozen") is True and flags.get("eq") is not False

    def _default(self, annotation: ast.expr, value: ast.expr) -> ast.expr | None:
        """The default of a field, if the caller gets one: ``value``, or that of ``field()``."""
        if isinstance(annotation, ast.Subscript):
            annotation = annotation.value
        if self.imports.qualified_names(annotation) & _CLASSVARS:
            return None
        if not (
            isinstance(value, ast.Call)
            and _FIELD in self.imports.qualified_names(value.func)
        ):
            return value
        arguments = {keyword.arg: keyword.value for keyword in value.keywords}
        init = arguments.get("init")
        if isinstance(init, ast.Constant) and init.value is False:
            return None
        return arguments.get("default") or arguments.get("default_factory")
