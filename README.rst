tukuroi is an **unofficial fork** of `Instagram/Fixit
<https://github.com/Instagram/Fixit>`_, the linting framework that Meta
published. It is not affiliated with Meta, nor endorsed by Meta or by the
maintainers of Fixit. Its main differences from upstream:

- The rules run on a new engine, ``tukuroi.core``, built on Python's ``ast``
  module in place of LibCST.
- Safer handling of untrusted repositories: ``--no-custom-rules`` keeps
  tukuroi from importing any rules but its built-in ones, the search for
  configurations stops at the root of the repository, output templates take
  only the names of their fields, and the LSP server talks over stdio only.
- It supports only the two newest minor versions of CPython: 3.14 and 3.15.

tukuroi provides a highly configurable linting framework with support for
auto-fixes, custom "local" lint rules, and hierarchical configuration, built
on Python's ``ast`` module. A fix replaces only the code that it fixes; a
project can choose to format the fixed files with
`ruff <https://docs.astral.sh/ruff/>`_ (``pip install "tukuroi[ruff]"``).

tukuroi makes it quick and easy to write new lint rules and offer suggested
changes for any errors found, which can then be accepted automatically,
or presented to the user for consideration.

For more details, see the `user guide`__ in ``docs/``.

.. __: https://github.com/Fkinds/tukuroi/tree/main/docs/guide

.. QUICKSTART


Coming from Fixit
-----------------

tukuroi reads none of the names of Fixit. Rename them:

.. list-table::
    :header-rows: 1

    * - Fixit
      - tukuroi
    * - ``pip install fixit``
      - ``pip install tukuroi``
    * - ``fixit lint``, ``python -m fixit``
      - ``tukuroi lint``, ``python -m tukuroi``
    * - ``[tool.fixit]``, ``[[tool.fixit.overrides]]``
      - ``[tool.tukuroi]``, ``[[tool.tukuroi.overrides]]``
    * - ``fixit.toml``, ``.fixit.toml``
      - ``tukuroi.toml``, ``.tukuroi.toml``
    * - ``FIXIT_CUSTOM_RULES``
      - ``TUKUROI_CUSTOM_RULES``
    * - ``fixit.rules``
      - ``tukuroi.rules``, with fewer rules: ruff has the others (see the
        `ruff guide`__)
    * - the pre-commit hooks ``fixit-lint`` and ``fixit-fix``
      - ``tukuroi-lint`` and ``tukuroi-fix``

.. __: https://github.com/Fkinds/tukuroi/blob/main/docs/guide/ruff.rst

The settings of Fixit that tukuroi does not support (``python-version``,
``options``, ``tags``) are configuration errors that say so. ``formatter`` takes
``"ruff"`` or ``"none"`` only, not ``"black"`` or ``"ufmt"``.

The rules of Fixit do not run on tukuroi: they are written for LibCST, and
tukuroi uses ``ast``. To port a rule:

.. list-table::
    :header-rows: 1

    * - Fixit
      - tukuroi
    * - a subclass of ``fixit.LintRule``, visiting LibCST nodes
      - a subclass of ``tukuroi.Rule``, with ``visit_<node>`` methods named
        after the classes of ``ast``
    * - ``METADATA_DEPENDENCIES`` and ``QualifiedNameProvider``
      - ``self.imports.qualified_names(node)``
    * - a LibCST node as the ``replacement``
      - a string as the ``replacement``, or ``edits`` over the original text
    * - ``fixit.testing.add_lint_rule_tests_to_module``
      - ``tukuroi.testing.add_rule_tests_to_module``
    * - ``fixit.config.collect_rules(Config(...))``
      - ``tukuroi.config.load_rules(Config(...))``; ``Config`` has no
        ``python_version``

See `Writing Rules`__ for the details.

.. __: https://github.com/Fkinds/tukuroi/blob/main/docs/guide/rules.rst


License
-------

tukuroi is `MIT licensed`__, as found in the LICENSE file.

.. __: https://github.com/Fkinds/tukuroi/blob/main/LICENSE
