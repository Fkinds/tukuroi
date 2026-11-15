# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast
from dataclasses import dataclass

from ...core.rule import Invalid, Rule, Valid
from ...core.text import Position

_CLASSVARS = {"typing.ClassVar", "typing_extensions.ClassVar"}
_ATTRS_FIELDS = frozenset(
    {"attr.attr", "attr.attrib", "attr.field", "attr.ib", "attrs.field"}
)


@dataclass(frozen=True, slots=True)
class _Maker:
    """A decorator that makes a class of fields, without its arguments."""

    # Whether the class is frozen.
    frozen: bool
    # Whether each annotation is a field: None when attrs guesses it.
    auto_attribs: bool | None
    # The calls that make a field.
    fields: frozenset[str]


_DATACLASS = _Maker(False, True, frozenset({"dataclasses.field"}))
_ATTRS_FROZEN = _Maker(True, None, _ATTRS_FIELDS)
_ATTRS_DEFINE = _Maker(False, None, _ATTRS_FIELDS)
_ATTR_S = _Maker(False, False, _ATTRS_FIELDS)
_MAKERS = {
    "dataclasses.dataclass": _DATACLASS,
    "attrs.frozen": _ATTRS_FROZEN,
    "attr.frozen": _ATTRS_FROZEN,
    "attrs.define": _ATTRS_DEFINE,
    "attrs.mutable": _ATTRS_DEFINE,
    "attr.define": _ATTRS_DEFINE,
    "attr.mutable": _ATTRS_DEFINE,
    "attr.s": _ATTR_S,
    "attr.attrs": _ATTR_S,
    "attr.attributes": _ATTR_S,
    "attr.dataclass": _Maker(False, True, _ATTRS_FIELDS),
}

# The value of an argument that is not a literal.
_UNKNOWN = object()


def _literal(
    arguments: dict[str | None, ast.expr], name: str, default: object
) -> object:
    """The argument ``name``: ``default`` without it, ``_UNKNOWN`` if not a literal."""
    value = arguments.get(name)
    if value is None:
        return default
    return value.value if isinstance(value, ast.Constant) else _UNKNOWN


class NoValueObjectDefault(Rule):
    """
    A value object takes every value of its fields from its caller: no field
    has a default, which the caller would get without writing it. Explicit is
    better than implicit.

    A value object is a frozen class that is equal to the objects of the same
    values: one of ``@dataclass(frozen=True)``, or of attrs, ``@attrs.frozen``,
    ``@attrs.define(frozen=True)`` or ``@attr.s(frozen=True)``. A frozen class
    with ``eq=False`` (or ``cmp=False`` of ``attr.s``) is an entity, equal to
    the objects of its identity only, and may give its ``id`` a default. The
    fields that the caller does not pass keep theirs: ``field(init=False)``
    (``attr.ib(init=False)``), and what is not a field: the ``ClassVar``
    annotations, and the annotations that attrs does not take as fields, those
    of ``attr.s`` without ``auto_attribs=True``, and those of a class with an
    ``attr.ib()`` that has no annotation.

    Only ``eq=False`` tells an entity from a value object: give it to each
    frozen entity. A frozen class that is neither, such as settings frozen so
    that nothing changes them, is reported too: keep a default with
    ``# lint-ignore: NoValueObjectDefault`` at the end of the last line of its
    field or on the line above the field, or do not enable the rule for the
    files of the class.
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
        # A class attribute, without an annotation.
        Valid(
            """
            from dataclasses import dataclass

            @dataclass(frozen=True)
            class Money:
                LIMIT = 100
                amount: int
            """
        ),
        # The entities of attrs.
        Valid(
            """
            import uuid
            import attrs

            @attrs.frozen(eq=False)
            class Order:
                id: uuid.UUID = attrs.field(factory=uuid.uuid4)
            """
        ),
        Valid(
            """
            import attr

            @attr.s(frozen=True, cmp=False)
            class Order:
                id = attr.ib(default=0)
            """
        ),
        Valid(
            """
            from attrs import define, field

            @define
            class Options:
                debug: bool = False
                paths: list[str] = field(factory=list)
            """
        ),
        Valid(
            """
            import attrs

            @attrs.frozen
            class Money:
                amount: int
                cents: int = attrs.field(init=False, default=0)
            """
        ),
        # Without auto_attribs=True, attr.s takes the calls of attr.ib only.
        Valid(
            """
            import attr

            @attr.s(frozen=True)
            class Money:
                LIMIT: int = 100
                SCALE = 2
                amount = attr.ib()
            """
        ),
        # So does attrs.frozen, with a field without an annotation.
        Valid(
            """
            import attr
            import attrs

            @attrs.frozen
            class Money:
                LIMIT: int = 100
                amount = attr.ib()
            """
        ),
        # Only a literal auto_attribs=True makes each annotation a field.
        Valid(
            """
            import attr

            AUTO = True

            @attr.s(frozen=True, auto_attribs=AUTO)
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
        # The value objects of attrs.
        Invalid(
            """
            import attrs

            @attrs.frozen
            class Money:
                amount: int = 0
            """,
            position=Position(5, 18),
        ),
        Invalid(
            """
            from attrs import define

            @define(frozen=True, kw_only=True)
            class Price:
                currency: str = "JPY"
            """,
            position=Position(5, 20),
        ),
        Invalid(
            """
            import attr

            @attr.s(frozen=True)
            class Money:
                amount = attr.ib(0)
            """,
            position=Position(5, 21),
        ),
        Invalid(
            """
            import attr

            @attr.frozen
            class Basket:
                items: list[str] = attr.field(factory=list)
            """,
            position=Position(5, 42),
        ),
        Invalid(
            """
            import attr

            @attr.s(frozen=True, auto_attribs=True)
            class Basket:
                items: list[str] = attr.Factory(list)
            """,
            position=Position(5, 23),
        ),
        Invalid(
            """
            import attr

            @attr.dataclass(frozen=True)
            class Money:
                amount: int = attr.ib(default=0)
            """,
            position=Position(5, 34),
        ),
    )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        found = next(filter(None, map(self._value_object, node.decorator_list)), None)
        if found is None:
            return
        maker, auto_attribs = found
        if auto_attribs is None:
            # As attrs guesses: unless a field has no annotation.
            auto_attribs = not any(
                isinstance(statement, ast.Assign)
                and self._field(maker, statement.value)
                for statement in node.body
            )
        for statement in node.body:
            default = self._default(maker, auto_attribs, statement)
            if default is not None:
                self.report(default)

    def _value_object(self, decorator: ast.expr) -> tuple[_Maker, bool | None] | None:
        """
        How ``decorator`` makes a value object, with whether each annotation
        is a field (None: as attrs guesses it); None if it makes none.
        """
        if isinstance(decorator, ast.Call):
            func, keywords = decorator.func, decorator.keywords
        else:
            func, keywords = decorator, []
        names = sorted(self.imports.qualified_names(func) & _MAKERS.keys())
        if not names:
            return None
        maker = _MAKERS[names[0]]
        arguments = {keyword.arg: keyword.value for keyword in keywords}
        if _literal(arguments, "frozen", maker.frozen) is not True:
            return None
        if False in (_literal(arguments, "eq", None), _literal(arguments, "cmp", None)):
            return None
        auto_attribs = _literal(arguments, "auto_attribs", maker.auto_attribs)
        if auto_attribs is None or isinstance(auto_attribs, bool):
            return maker, auto_attribs
        # Not a literal: only the calls of a field are fields.
        return maker, False

    def _field(self, maker: _Maker, value: ast.expr) -> ast.Call | None:
        """``value``, if it is a call that makes a field of ``maker``."""
        if isinstance(value, ast.Call) and (
            self.imports.qualified_names(value.func) & maker.fields
        ):
            return value
        return None

    def _default(
        self, maker: _Maker, auto_attribs: bool, statement: ast.stmt
    ) -> ast.expr | None:
        """The default of the field of ``statement``, if it is one that the caller gets."""
        if isinstance(statement, ast.Assign):
            # A field without an annotation, as attrs takes it.
            call = self._field(maker, statement.value)
            return None if call is None else self._field_default(call)
        if not isinstance(statement, ast.AnnAssign) or statement.value is None:
            return None
        annotation = statement.annotation
        if isinstance(annotation, ast.Subscript):
            annotation = annotation.value
        if self.imports.qualified_names(annotation) & _CLASSVARS:
            return None
        call = self._field(maker, statement.value)
        if call is not None:
            return self._field_default(call)
        return statement.value if auto_attribs else None

    def _field_default(self, call: ast.Call) -> ast.expr | None:
        """The default of the field that ``call`` makes, if the caller gets one."""
        arguments = {keyword.arg: keyword.value for keyword in call.keywords}
        init = arguments.get("init")
        if isinstance(init, ast.Constant) and init.value is False:
            return None
        # attr.ib() takes the default as its first argument too.
        if call.args:
            return call.args[0]
        return (
            arguments.get("default")
            or arguments.get("default_factory")
            or arguments.get("factory")
        )
