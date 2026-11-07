# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import os

from fixit.config import collect_rules
from fixit.ftypes import Config, QualifiedRule
from fixit.testing import add_lint_rule_tests_to_module

from .characterization_cli import CliCharacterizationTest
from .characterization_config import ConfigCharacterizationTest
from .characterization_custom_rules import CustomRulesCharacterizationTest
from .characterization_fix import FixCharacterizationTest
from .characterization_lsp import LspCharacterizationTest
from .characterization_suppression import SuppressionCharacterizationTest
from .config import ConfigTest
from .custom_rules_switch import CustomRulesSwitchTest
from .engine import EngineTest
from .ftypes import TypesTest
from .rule import RuleTest, RunnerTest
from .smoke import SmokeTest

# Expect the default of the switch for custom rules, even when the shell sets
# FIXIT_CUSTOM_RULES (see "Security" in the docs). custom_rules_switch sets it
# where it needs it. Every test module imports this package first.
os.environ.pop("FIXIT_CUSTOM_RULES", None)

add_lint_rule_tests_to_module(
    globals(),
    collect_rules(
        Config(
            enable=[
                QualifiedRule("fixit.rules"),
                QualifiedRule("fixit.upgrade"),
            ],
            python_version=None,
        )
    ),
)
