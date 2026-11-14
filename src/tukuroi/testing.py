# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of lint rules from their ``VALID`` and ``INVALID`` cases, for the authors
of rules: the names of :mod:`tukuroi.core.testing`, where the test cases say they
are (``tukuroi.testing.<rule>``).
"""

from .core.testing import RuleTestCase, add_rule_tests_to_module, generate_test_cases

__all__ = ["RuleTestCase", "add_rule_tests_to_module", "generate_test_cases"]
