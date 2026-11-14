# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests of ``tukuroi.util.capture`` (#116)."""

from collections.abc import Generator
from unittest import TestCase

from ..util import capture


def echo() -> Generator[object, object, str]:
    """Yield 1, then what it is sent, and return "done"."""
    sent = yield 1
    yield sent
    return "done"


class CaptureTest(TestCase):
    def test_send(self) -> None:
        # A value sent to the iterator goes to the generator, as respond().
        captured = capture(echo())
        iterator = iter(captured)
        self.assertEqual(next(iterator), 1)
        self.assertEqual(iterator.send("x"), "x")
        with self.assertRaises(StopIteration):
            next(iterator)
        self.assertEqual(captured.result, "done")

    def test_result_before_the_end(self) -> None:
        captured = capture(echo())
        with self.assertRaisesRegex(ValueError, "Generator hasn't completed"):
            _ = captured.result
