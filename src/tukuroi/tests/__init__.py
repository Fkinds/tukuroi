# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import os

from tukuroi.core.loader import RuleName, import_rules
from tukuroi.core.testing import generate_test_cases

from .api import (
    CommandTest,
    FixitBytesTest,
    FixitPathsTest,
    FixitStdinAndFileTest,
    PrintResultTest,
    PublicNamesTest,
)
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
from .core_loader import (
    CollectRulesTest,
    ImportRulesTest,
    LoaderRuleNameTest,
    LoadTest,
)
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
from .examples import ExamplesTest
from .ftypes import TypesTest
from .lsp import DebounceTest
from .pool import PoolTest
from .rules_strict import StrictRulesTest
from .smoke import SmokeTest
from .template import TemplateTest
from .util import CaptureTest

# Expect the default of the switch for custom rules, even when the shell sets
# TUKUROI_CUSTOM_RULES (see "Security" in the docs). custom_rules_switch sets it
# where it needs it. Every test module imports this package first.
os.environ.pop("TUKUROI_CUSTOM_RULES", None)

# The test cases of the built-in rules, named after each rule: those enabled by
# default, and the strict ones (#123).
for _package in ("tukuroi.rules", "tukuroi.rules.strict"):
    for _case in generate_test_cases(import_rules(RuleName(_package))):
        globals()[_case.__name__] = _case
del _package, _case
