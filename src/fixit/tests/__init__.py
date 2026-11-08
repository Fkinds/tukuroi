# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import os

from fixit.api import CORE_ENGINE
from fixit.config import collect_rules
from fixit.core.loader import RuleName, import_rules
from fixit.core.testing import generate_test_cases
from fixit.ftypes import Config, QualifiedRule
from fixit.testing import add_lint_rule_tests_to_module

from .api import CommandTest, FixitBytesTest
from .characterization_cli import CliCharacterizationTest
from .characterization_config import ConfigCharacterizationTest
from .characterization_custom_rules import CustomRulesCharacterizationTest
from .characterization_fix import FixCharacterizationTest
from .characterization_lsp import LspCharacterizationTest
from .characterization_suppression import SuppressionCharacterizationTest
from .config import ConfigTest
from .config_load_rules import LoadRulesTest
from .core_directives import DirectiveCoversTest, ParseDirectivesTest
from .core_edits import ApplyFixesTest, CheckFixTest, DropsCommentsTest
from .core_engine import DispatchTest, ReportsTest
from .core_fix import FixTest, RuffFormatTest
from .core_imports import AddImportTest
from .core_loader import CollectRulesTest, ImportRulesTest, LoaderRuleNameTest
from .core_names import ImportTableTest
from .core_rule import RuleCasesTest, RuleNameTest, RuleReportTest, RuleVisitsTest
from .core_source import (
    SourceContentTest,
    SourceFromBytesTest,
    SourceFromTextTest,
    SourceParseErrorTest,
)
from .core_suppression import (
    AnnotationTest,
    BlockFooterTest,
    ClauseTest,
    DecoratorTest,
    IsSuppressedTest,
    ItemTest,
    StatementTest,
)
from .core_testing import GenerateTestCasesTest
from .core_text import LineIndexTest, PositionTest, RangeTest, SpanTest
from .custom_rules_switch import CustomRulesSwitchTest
from .engine import EngineTest
from .ftypes import TypesTest
from .rule import RuleTest, RunnerTest
from .smoke import SmokeTest

# Expect the default of the switch for custom rules, even when the shell sets
# FIXIT_CUSTOM_RULES (see "Security" in the docs). custom_rules_switch sets it
# where it needs it. Every test module imports this package first.
os.environ.pop("FIXIT_CUSTOM_RULES", None)
# Temporary (#21): the libcst engine, but in the tests that set it.
os.environ.pop(CORE_ENGINE, None)

# The test cases of the rules of the new engine (#21), named after each rule with
# "Core" in front: the rules of the libcst engine have the same names.
for _case in generate_test_cases(import_rules(RuleName("fixit.core.rules"))):
    globals()[f"Core{_case.__name__}"] = _case
del _case

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
