# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import unittest


# Triggers built-in lint rules
class FooTest(unittest.TestCase):
    def test_bar(self) -> None:
        self.assertTrue(value in values)
        if True:
            self.assertTrue(value, None)

    def test_ignored(self) -> None:
        # lint-fixme: SomethingUnrelated
        self.assertTrue(one in many)

        # lint-ignore
        self.assertTrue(two in many)

        # lint-fixme: UseAssertIn
        self.assertTrue(three in many)

        self.assertTrue(four in many)  # lint-ignore: UseAssertIn
