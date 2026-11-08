Quick Start
-----------


Setup
^^^^^

Install Fixit from PyPI:

.. code-block:: console

    $ pip install --pre "fixit >1"

By default, Fixit enables all of the lint rules that ship with Fixit,
all of which are part of the :mod:`fixit.rules` package.

If you want to customize the list of enabled rules, either to add new rules
or disable others, see the :ref:`Configuration Guide <configuration>` for
details and options available.

Fixit offers multiple integrations, including pre-commit actions and LSP support
for VSCode and other editors. See the :ref:`Integrations Guide <integrations>`
for details.


Usage
^^^^^

See lints and suggested changes for a set of source files:

.. code-block:: console

    $ fixit lint <path>

Apply suggested changes on those same files automatically:

.. code-block:: console

    $ fixit fix <path>

If given directories, Fixit will automatically recurse them, finding any files
with the ``.py`` extension, while obeying your repo's global ``.gitignore``.

See the :ref:`Command Reference <commands>` for more details.

Example
^^^^^^^

Given the following code:

.. code:: python

    # foo_test.py

    import unittest


    class FooTest(unittest.TestCase):
        def test_bar(self) -> None:
            self.assertTrue(value in values)
            if True:
                self.assertTrue(value, None)

When running Fixit, we see three separate lint errors:

.. code:: console

    $ fixit lint foo_test.py
    foo_test.py@8:8 UseAssertIn: Use assertIn/assertNotIn instead of assertTrue/assertFalse for inclusion check.
    See https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertIn) (has autofix)
    foo_test.py@9:8 NoStaticIfCondition: Your if condition appears to evaluate to a static value (e.g. `or True`, `and False`). Please double check this logic and if it is actually temporary debug code.
    foo_test.py@10:12 NoAssertTrueForComparisons: "assertTrue" does not compare its arguments, use "assertEqual" or other appropriate functions. (has autofix)
    🛠️  1 file checked, 1 file with errors, 2 auto-fixes available 🛠️

We can also see any suggested changes by passing ``--diff``:

.. code:: console

    $ fixit lint --diff foo_test.py
    foo_test.py@8:8 UseAssertIn: Use assertIn/assertNotIn instead of assertTrue/assertFalse for inclusion check.
    See https://docs.python.org/3/library/unittest.html#unittest.TestCase.assertIn) (has autofix)
    --- a/foo_test.py
    +++ b/foo_test.py
    @@ -7,3 +7,3 @@
         def test_bar(self) -> None:
    -        self.assertTrue(value in values)
    +        self.assertIn(value, values)
             if True:
    ...

Fixit checks the rules that come with it (see :ref:`builtin-rules`); ruff
covers the others that Fixit used to have (see :ref:`ruff-rules`). To write
rules of your own, see :ref:`writing-rules`.


.. _suppressions:

Silencing Errors
^^^^^^^^^^^^^^^^

For lint rules without autofixes, it may still be useful to silence individual
errors. A simple ``# lint-ignore`` or ``# lint-fixme`` comment, either as
a trailing inline comment, or as a dedicated comment line above the code that
triggered the lint rule:

.. code:: python

    self.assertTrue(a in b)  # lint-fixme: UseAssertIn

    # lint-ignore: UseAssertIn
    self.assertTrue(c in d)

By providing one or more lint rule, separated by commas, Fixit can still report
issues triggered by other lint rules that haven't been listed in the comment,
but this is not required. The names follow a ``:``, and must have the same
case as the names of the rules, with or without ``Rule`` at the end. A
directive that does not fit this form silences nothing, and Fixit warns about
it (``invalid lint-ignore directive``). A comment can hold other tools'
directives too: ``# noqa  # lint-ignore: UseAssertIn``.

If no rule name is listed, Fixit will silence all rules when reported on code
associated with that comment:

.. code-block:: python

    self.assertTrue(a in b)  # lint-ignore


"ignore" vs "fixme"
%%%%%%%%%%%%%%%%%%%

Both comment directives achieve the same result — silencing errors for
a particular statement of code. The semantics of using either term is left to
the user, though they are intended to be used with the following meanings:

- ``# lint-fixme`` for errors that need to be corrected or reviewed at a later
  date, but where the lint rule should be silenced temporarily for the sake
  of CI or similar external circumstances.

- ``# lint-ignore`` for errors that are false-positives (please report issues
  if this occurs with built-in lint rules) or the code is otherwise
  intentionally written or structured in a way that the lint error cannot
  be avoided.

Future versions of Fixit may offer reporting or similar tools that treat
"fixme" directives differently from "ignore" directives.
