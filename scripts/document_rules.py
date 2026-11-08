# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from collections.abc import Sequence
from pathlib import Path
from textwrap import dedent, indent

from jinja2 import Template

from fixit.core.loader import RuleName, import_rules
from fixit.core.rule import Invalid, Rule, Valid

# The packages of the built-in rules, as configs name them.
RULES = ["fixit.rules"]

RULES_DOC = Path(__file__).parent.parent / "docs" / "guide" / "builtins.rst"

PAGE_TPL = Template(
    r"""
..
   THIS FILE IS GENERATED - DO NOT EDIT BY HAND!
   Run `make html` or `scripts/document_rules.py` to regenerate this file.

.. _builtin-rules:

Built-in Rules
--------------

{% for name in packages %}
- :mod:`{{ name }}`
{% endfor %}

{% for name, (module, rules) in packages.items() %}

``{{ name }}``
^^^^{{ "^" * len(name) }}

.. automodule:: {{ module }}

{% for rule in rules %}
- :class:`{{rule.__name__}}`
{% endfor %}

{% for rule in rules %}
.. class:: {{ rule.__name__ }}

{{ redent(rule.__doc__, "    ") }}

{% if rule.MESSAGE %}
    .. attribute:: MESSAGE
        :no-index:

{{ redent(rule.MESSAGE, "        ") }}

{% endif %}
{% if fixes(rule) %}
    .. attribute:: AUTOFIX
        :no-index:
        :type: Yes

{% endif %}
    .. attribute:: VALID
        :no-index:

{% for case in valid(rule)[:2] %}
        .. code:: python

{{ redent(case.code, "            ") }}
{% endfor %}

    .. attribute:: INVALID
        :no-index:

{% for case in invalid(rule)[:2] %}
        .. code:: python

{{ redent(case.code, "            ") }}
{% if case.expected_replacement %}

            # suggested fix
{{ redent(case.expected_replacement, "            ") }}

{% endif %}
{% endfor %}
{% endfor %}
{% endfor %}
    """,
    trim_blocks=True,
    lstrip_blocks=True,
)


def redent(value: str, prefix: str = "") -> str:
    return indent(dedent(value).strip("\n"), prefix).rstrip()


def valid(rule: type[Rule]) -> Sequence[Valid]:
    return [Valid(c) if isinstance(c, str) else c for c in rule.VALID]


def invalid(rule: type[Rule]) -> Sequence[Invalid]:
    return [Invalid(c) if isinstance(c, str) else c for c in rule.INVALID]


def fixes(rule: type[Rule]) -> bool:
    """Whether the rule fixes what it reports: a case of it gives the fix."""
    return any(case.expected_replacement for case in invalid(rule))


def main() -> None:
    packages = {}
    for name in RULES:
        rules = import_rules(RuleName(name))
        # The package that the rules are in: a module of it each.
        packages[name] = (rules[0].__module__.rpartition(".")[0], rules)

    RULES_DOC.write_text(
        PAGE_TPL.render(
            dedent=dedent,
            indent=indent,
            redent=redent,
            fixes=fixes,
            invalid=invalid,
            len=len,
            packages=packages,
            valid=valid,
        )
    )


if __name__ == "__main__":
    main()
