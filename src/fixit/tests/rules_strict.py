# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The strict rules of :mod:`fixit.rules.strict` (#123): what their test cases do
not check. The cases check one report each; these, every report of a class, and
how the rules load.
"""

from pathlib import Path
from textwrap import dedent
from unittest import TestCase

from ..config import load_rules
from ..core.engine import lint
from ..core.loader import RuleName, import_rules
from ..core.source import Source
from ..core.text import Position
from ..ftypes import Config, QualifiedRule
from ..rules.strict.no_value_object_default import NoValueObjectDefault

CODE = dedent(
    """\
    from dataclasses import dataclass, field
    from decimal import Decimal
    from typing import ClassVar

    @dataclass(frozen=True)
    class Money:
        LIMIT: ClassVar[int] = 100
        amount: int = 0
        currency: str = field(default="JPY")
        cents: int = field(init=False, default=0)
        tags: tuple[str, ...] = field(default_factory=tuple)
        limit: Decimal = Decimal("0")
    """
)


class StrictRulesTest(TestCase):
    def test_every_default(self) -> None:
        """Each field with a default, once, at its default: none of the others."""
        reports = lint(Source.from_text(CODE), [NoValueObjectDefault]).reports
        positions = [report.position for report in reports]
        expected = [Position(8, 18), Position(9, 34), Position(11, 50)]
        # A call that is not field() is a default too.
        expected.append(Position(12, 21))
        self.assertEqual(positions, expected)

    def test_not_in_fixit_rules(self) -> None:
        """Enabling fixit.rules does not enable them: its subpackages are apart."""
        names = [rule.name() for rule in import_rules(RuleName("fixit.rules"))]
        self.assertNotIn("NoValueObjectDefault", names)
        strict = import_rules(RuleName("fixit.rules.strict"))
        self.assertEqual(list(strict), [NoValueObjectDefault])

    def test_builtin(self) -> None:
        """They come with Fixit: they load with the custom rules turned off."""
        self.assertTrue(QualifiedRule("fixit.rules.strict").builtin)
        config = Config(
            root=Path.cwd(),
            custom_rules=False,
            enable=[QualifiedRule("fixit.rules.strict")],
        )
        self.assertEqual(load_rules(config), (NoValueObjectDefault,))
