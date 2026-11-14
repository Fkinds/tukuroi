.. _writing-rules:

Writing Rules
-------------

tukuroi makes it easy to write new lint rules, directly in your codebase
alongside the code they lint. A rule finds code in the syntax tree of Python's
:mod:`ast` module, and fixes it by replacing ranges of the original text: the
rest of the file stays as it was, comments included. tukuroi then formats each
file it fixes with ``ruff format``.

A Rule
^^^^^^

A rule is a subclass of :class:`tukuroi.Rule`, with a message, examples of code
it accepts and reports, and ``visit_<node>`` methods named after the classes of
:mod:`ast`:

.. code:: python

    # teambread/rules/hollywood.py

    import ast

    from tukuroi import Invalid, Rule, Valid


    class HollywoodName(Rule):
        MESSAGE = "It's underproved!"
        VALID = (
            Valid('name = "Susan"\n'),
            Valid('print("Terry")\n'),
        )
        INVALID = (
            Invalid('name = "Paul"\n', expected_replacement='name = "Mary"\n'),
            Invalid("print('Paul')\n", expected_replacement='print("Mary")\n'),
        )

        def visit_Constant(self, node: ast.Constant) -> None:
            if node.value == "Paul":
                self.report(node, replacement='"Mary"')

- ``MESSAGE`` is the message of a report that gives none. The name of the rule
  is the name of its class, without a ``Rule`` at its end.
- tukuroi walks the tree once, parents before children, and calls the methods of
  every rule for each node. ``visit_stmt`` or ``visit_expr`` takes every node of
  that kind; the most specific method runs first.
- ``self.report(node, message=None, *, replacement=None, edits=())`` reports
  ``node``, at the start of its range. Without ``replacement`` or ``edits``, the
  report has no fix.

Fixes
^^^^^

A fix is ``replacement``, a string for the text of the node reported, or
``edits``, a list of :class:`tukuroi.Edit`: each replaces a :class:`tukuroi.Span`
of the text, and an empty span inserts. Build them from the original text, so
that quotes, comments and spacing stay as they are:

- ``self.source.text`` is the text of the file, and ``self.source.span(node)``
  the span of a node in it. ``self.source.comments`` and ``self.source.tokens``
  come from :mod:`tokenize`.
- ``self.imports.qualified_names(node)`` tells what a name or an attribute
  refers to through the imports of the module: with ``import typing as t``,
  ``t.Callable`` is ``typing.Callable``. Names bound again after the import are
  not followed.
- ``tukuroi.core.imports.add_import`` gives the name to use for a module or a
  name of it, and the edit that imports it when the file does not yet.

tukuroi applies the fixes of a file in the order of their start, and skips one
that overlaps a fix applied before it. Then it lints the result again, until no
fix is left (at most 100 rounds). A fix that would drop a comment inside the
range it replaces is not applied: the report has no fix.

Tests
^^^^^

``VALID`` and ``INVALID`` are the tests of the rule. A valid case must not be
reported. An invalid case must be reported, with ``expected_message`` and
``position`` (a :class:`tukuroi.Position`) when given. When the rule fixes it,
the case must give ``expected_replacement``: the file after all the fixes and
``ruff format`` with its default settings.

Run them with :ref:`tukuroi test <test_command>`, or add them to a test module
of your own:

.. code:: python

    from tukuroi.testing import add_rule_tests_to_module

    from .rules.hollywood import HollywoodName

    add_rule_tests_to_module(globals(), [HollywoodName])

Enabling Rules
^^^^^^^^^^^^^^

Enable the rules in the project's :ref:`configuration` file:

.. code:: toml

    # teambread/pyproject.toml

    [tool.tukuroi]
    enable = [
        ".rules.hollywood",  # enable just the rules in hollywood.py
        ".rules",  # enable rules from all files in the rules/ directory
    ]

.. note::

    The leading ``.`` (period) is required when using in-repo, or "local", lint
    rules, with a module path relative to the directory containing the config
    file. This allows tukuroi to locate and import the lint rule without needing
    to install a plugin in the user's environment.

tukuroi imports each module of rules once in a process. After changing a rule,
restart :ref:`tukuroi lsp <lsp_command>` (or the editor that runs it) for the
change to take effect.

Rules run the code of the repo: see :ref:`security` before linting code you do
not trust.
