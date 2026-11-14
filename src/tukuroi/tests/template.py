# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests of the template of ``output-format = "custom"``: the names only (#14)."""

from pathlib import Path
from unittest import TestCase

from ..api import print_result
from ..core.text import Position, Range
from ..ftypes import OutputFormat, Result, Violation
from ..template import FIELDS, TemplateError, format_template, template_error

VALUES = {
    "end_col": 8,
    "end_line": 2,
    "message": "Bad.",
    "path": "sub/t.py",
    "rule_name": "NoBad",
    "start_col": 0,
    "start_line": 1,
}


class TemplateTest(TestCase):
    def test_format(self) -> None:
        cases = (
            # (template, line)
            ("{path}:{start_line}:{start_col} {rule_name}: {message}", "sub/t.py:1:0 NoBad: Bad."),
            ("{start_line}:{start_col}-{end_line}:{end_col}", "1:0-2:8"),
            # A format spec, a conversion, and a nested field are as before.
            ("{path:>10}|", "  sub/t.py|"),
            ("{start_line:03d}", "001"),
            ("{rule_name!r}", "'NoBad'"),
            ("{path:>{end_col}}|", "sub/t.py|"),
            ("{{path}}", "{path}"),
            ("no field", "no field"),
        )  # fmt: skip
        for template, line in cases:
            with self.subTest(template):
                self.assertEqual(format_template(template, VALUES), line)
                self.assertIsNone(template_error(template))

    def test_fields(self) -> None:
        self.assertEqual(sorted(FIELDS), sorted(VALUES))

    def test_errors(self) -> None:
        attribute = "uses an attribute or an index, which is not allowed"
        unknown = f"not one of {', '.join(map(repr, FIELDS))}"
        cases = (
            # (template, error)
            ("{path.parent}", f"'{{path.parent}}' {attribute}"),
            ("{path[0]}", f"'{{path[0]}}' {attribute}"),
            # In a nested field too.
            ("{path:{message.x}}", f"'{{message.x}}' {attribute}"),
            # `result` was the Result object, removed with its attributes.
            ("{result}", f"unknown field 'result', {unknown}"),
            (
                "{result.violation.message}",
                f"'{{result.violation.message}}' {attribute}",
            ),
            ("{nope}", f"unknown field 'nope', {unknown}"),
            ("{ path}", f"unknown field ' path', {unknown}"),
            ("{}", "a field without a name ('{}', '{0}') is not allowed"),
            ("{0}", "a field without a name ('{}', '{0}') is not allowed"),
            # The messages of str.format, and of the format spec of a value.
            ("{", "Single '{' encountered in format string"),
            ("}", "Single '}' encountered in format string"),
            ("{path:d}", "Unknown format code 'd' for object of type 'str'"),
            ("{start_line:s}", "Unknown format code 's' for object of type 'int'"),
        )
        for template, error in cases:
            with self.subTest(template):
                self.assertEqual(template_error(template), error)

    def test_attribute_raises_before_reading(self) -> None:
        # The value is not read: a str would have the attribute.
        with self.assertRaises(TemplateError):
            format_template("{path.upper}", VALUES)

    def test_print_result(self) -> None:
        # print_result, from the API, takes the names only too: the config and
        # --output-template are checked before, but it is not.
        where = Range(Position(1, 0), Position(2, 8))
        result = Result(Path.cwd() / "t.py", Violation("NoBad", where, "Bad.", False))
        custom = OutputFormat.custom
        with self.assertRaises(TemplateError):
            print_result(result, output_format=custom, output_template="{path.parent}")
