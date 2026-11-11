# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests of the debounce of the LSP, which the other tests turn off (#116)."""

import threading
import time
from unittest import TestCase

from ..lsp import Debouncer, debounce


class DebounceTest(TestCase):
    def test_no_interval(self) -> None:
        def f() -> None:
            pass

        self.assertIs(debounce(0)(f), f)

    def test_only_the_last_call(self) -> None:
        calls: list[int] = []
        called = threading.Event()

        def f(value: int) -> None:
            calls.append(value)
            called.set()

        debounced = debounce(0.05)(f)
        self.assertIsInstance(debounced, Debouncer)
        debounced(1)
        debounced(2)
        self.assertTrue(called.wait(5))
        # The first call was cancelled: it does not come later either.
        time.sleep(0.1)
        self.assertEqual(calls, [2])
