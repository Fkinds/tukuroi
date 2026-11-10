.. _commands:

Commands
--------

.. code:: console

    $ fixit [OPTIONS] COMMAND ...


The following options are available for all commands:

.. attribute:: --debug / --quiet

    Raise or lower the level of output and logging.

.. attribute:: --config-file PATH

    Override the normal hierarchical configuration and use the configuration
    from the specified path, ignoring all other configuration files entirely.
    Its :attr:`enable` and :attr:`disable` apply to every file, wherever it is.
    The paths of its :ref:`overrides`, and its local rules, are relative to the
    directory of the configuration file, as in any other.

.. attribute:: --custom-rules / --no-custom-rules

    Load custom rules, or turn them off. Custom rules are the rules that do not
    come with Fixit (anything but :mod:`fixit.rules`),
    such as local rules in the repo. Fixit loads them by default. See
    :ref:`security` for when to turn them off, and what Fixit does then.

    The environment variable ``FIXIT_CUSTOM_RULES`` sets the default, and the
    option wins over it. Fixit reads the variable as
    `Click <https://click.palletsprojects.com/>`_ reads a boolean, ignoring
    letter case:

    - ``1``, ``true``, ``t``, ``yes``, ``y``, ``on``: load custom rules.
    - ``0``, ``false``, ``f``, ``no``, ``n``, ``off``: turn them off.
    - Unset or empty: the default, load them.
    - Any other value is a usage error.

    No standard defines how to write a boolean in an environment variable, so
    these are the values that Click accepts.

.. attribute:: --output-format / -o FORMAT_TYPE

    Override how Fixit prints violations to the terminal.

    See :attr:`output-format` for available formats.

.. attribute:: --output-template TEMPLATE

    Override the python formatting template to use with ``output-format = 'custom'``.
    The same variables as in :attr:`output-template` are allowed, and nothing
    else: an invalid template is a usage error.

Any command exits with 2 on a usage error, and on a configuration that Fixit
cannot use: a file that is not TOML, or an invalid value. The error goes to
stderr, without a traceback. ``lint`` and ``fix`` read the configurations of
the current directory and of the directory of each file to lint, or the one
given with ``--config-file``, and load the rules that they name, before they
lint any file, and stop at the first error. A rule of ``--rules`` that cannot
be loaded is a usage error. No standard defines exit codes other than 0 and nonzero: 2 is the code
of Click and Ruff for these.

``lint``
^^^^^^^^

Lint one or more paths, and print a list of lint errors. If "-" is given as the
first path, then the second given path will be used for configuration lookup
and error messages, and the input read from STDIN. No other path may follow,
and "-" after another path is a usage error.

A path that does not exist is a usage error, before any file is linted. A
directory is walked for Python files, without the files that ``.gitignore``
has. A file given by name is linted, though ``.gitignore`` has it. A file
given twice, by name or in a directory, is linted once.

.. code:: console

    $ fixit lint [--diff] [PATH ...]

.. attribute:: --diff / -d

    Show suggested fixes, in unified diff format, when available. The diff
    names the file as the lint error does: relative to the current directory,
    or absolute outside it.

The exit code is 0 when no file has a lint error, 1 when a file has one, and 2
when Fixit could not lint a file (a syntax error, an exception in a rule, or a
configuration of the file that Fixit cannot use); 3 for both.


``fix``
^^^^^^^

Lint one or more paths, and apply suggested fixes. If "-" is given as the
first path, then the second given path will be used for configuration lookup,
the input read from STDIN, and the fixed output printed to STDOUT (ignoring
:attr:`--interactive`); the lint errors, and the diffs of ``--diff``, go to
STDERR. As with ``lint``, no other path may follow, and the paths are found the
same way.

.. code:: console

    $ fixit fix [--interactive | --automatic [--diff]] [PATH ...]

.. attribute:: --interactive / -i

    Interactively prompt the user to apply or decline suggested fixes for
    each auto-fix available. *default*

.. attribute:: --automatic / -a

    Automatically apply suggested fixes for all lint errors when available.

.. attribute:: --diff / -d

    Show applied fixes in unified diff format when applied automatically.

The exit code is that of ``lint``, for the lint errors left after the fixes,
as with ``ruff check --fix``: 1 only when a file still has one, because it has
no fix, or its fix was declined or could not be applied.


.. _lsp_command:

``lsp``
^^^^^^^

Start the language server providing IDE features over
`LSP <https://microsoft.github.io/language-server-protocol/>`__.
This command is only available if installed with the ``lsp`` extras (e.g.
``pip install "fixit[lsp]"``).  See :ref:`IDE Integrations <ide_integrations>`
for more details.

.. code:: console

    $ fixit lsp [--stdio] [--debounce-interval SECONDS]

The server talks over stdio only, with the editor that starts it.

.. attribute:: --stdio

    Serve LSP over stdio, as without it. Some clients pass it.

.. attribute:: --debounce-interval

    Delay in seconds for server-side debounce. *default: 0.5*


.. _test_command:

``test``
^^^^^^^^

Test one or more lint rules using their :attr:`~fixit.Rule.VALID` and
:attr:`~fixit.Rule.INVALID` test cases.

Expects qualified lint rule packages or names, with the same form as when
configuring :attr:`enable` and :attr:`disable`.

.. code:: console

    $ fixit test [RULES ...]

Example:

.. code:: console

    $ fixit test .rules
    test_INVALID_0 (fixit.testing.HollywoodName.test_INVALID_0) ... ok
    test_INVALID_1 (fixit.testing.HollywoodName.test_INVALID_1) ... ok
    test_VALID_0 (fixit.testing.HollywoodName.test_VALID_0) ... ok
    test_VALID_1 (fixit.testing.HollywoodName.test_VALID_1) ... ok

    ----------------------------------------------------------------------
    Ran 4 tests in 0.024s

    OK


``debug``
^^^^^^^^^

Debug options for validating Fixit configuration.

.. code:: console

    $ fixit debug [PATH ...]


``validate-config``
^^^^^^^^^^^^^^^^^^^

Check a configuration file, alone and as a root configuration, without linting
any file.

.. code:: console

    $ fixit validate-config PATH

Fixit reads the file as ``lint`` does, and stops at the first value that it
cannot use. Then it loads every rule that the file names, in :attr:`enable`,
:attr:`disable` and all the :ref:`overrides`, with its
:attr:`enable-root-import`, and reports each one that cannot be loaded. A file
without ``[tool.fixit]`` has nothing to check. As the file is checked alone, an
:attr:`enable-root-import` that is only wrong under a parent configuration is
not found: ``lint`` finds it.

Each error goes to stderr, in the form of ``lint``:

.. code:: console

    $ fixit validate-config pyproject.toml
    Error: pyproject.toml: enable: could not find rule fixit.rules:Nope

The exit code is 0 when the file is valid, and 2 when it is not, as for any
configuration that Fixit cannot use. With custom rules turned off
(``--no-custom-rules``), only the names of custom rules are checked, with a
warning that they are skipped; see :ref:`security`.
