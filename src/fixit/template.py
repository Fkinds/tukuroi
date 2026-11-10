# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The template of ``output-format = "custom"`` (#14): a format string of
:meth:`str.format`, with the names of :data:`FIELDS` only. A field with an
attribute or an index (``{path.parent}``, ``{path[0]}``) is refused, so that a
template reads nothing but the values given, which are strings and numbers.
"""

import string
from collections.abc import Mapping, Sequence
from typing import Any

# The fields of a template, and a value of each, to check a template with.
SAMPLE: Mapping[str, str | int] = {
    "end_col": 0,
    "end_line": 1,
    "message": "",
    "path": "",
    "rule_name": "",
    "start_col": 0,
    "start_line": 1,
}
FIELDS = tuple(SAMPLE)


class TemplateError(ValueError):
    """A field of a template that is not one of :data:`FIELDS`, by name."""


class _Formatter(string.Formatter):
    def get_field(
        self, field_name: str, args: Sequence[Any], kwargs: Mapping[str, Any]
    ) -> tuple[Any, str]:
        # The nested fields of a format spec come here too.
        if "." in field_name or "[" in field_name:
            raise TemplateError(
                f"'{{{field_name}}}' uses an attribute or an index, which is not allowed"
            )
        # "{}" comes as "0": the format string numbers it.
        if field_name.isdigit():
            raise TemplateError("a field without a name ('{}', '{0}') is not allowed")
        if field_name not in kwargs:
            choices = ", ".join(map(repr, FIELDS))
            raise TemplateError(f"unknown field {field_name!r}, not one of {choices}")
        return kwargs[field_name], field_name


def format_template(template: str, values: Mapping[str, str | int]) -> str:
    """
    ``template`` with ``values``, the fields of a violation. Raises a
    :class:`TemplateError`, or the ValueError of :meth:`str.format` for a
    template that is not a format string, or a format spec that is wrong.
    """
    return _Formatter().vformat(template, (), values)


def template_error(template: str) -> str | None:
    """What is wrong with ``template``, if anything, found by formatting it."""
    try:
        format_template(template, SAMPLE)
    # A format spec that a string or a number does not take is a ValueError.
    except ValueError as error:
        return str(error)
    return None
