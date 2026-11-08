# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import ast

from fixit import Invalid, Rule, Valid


class HollywoodName(Rule):
    MESSAGE = "It's underproved!"
    # clean code samples
    VALID = (
        Valid('name = "Susan"\n'),
        Valid('print("Terry")\n'),
    )
    # code that triggers this rule
    INVALID = (
        Invalid('name = "Paul"\n', expected_replacement='name = "Mary"\n'),
        Invalid("print('Paul')\n", expected_replacement='print("Mary")\n'),
    )

    def visit_Constant(self, node: ast.Constant) -> None:
        if node.value == "Paul":
            self.report(node, replacement='"Mary"')
