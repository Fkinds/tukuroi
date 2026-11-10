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

Any command exits with 2 on a usage error, and on a configuration that Fixit
cannot use: a file that is not TOML, or an invalid value. The error goes to
stderr, without a traceback. ``lint`` and ``fix`` read the configuration of the
current directory, or the one given with ``--config-file``, before any file,
and stop there. An error in the configuration of a file in another directory is
an error of that file. No standard defines exit codes other than 0 and nonzero:
2 is the code of Click and Ruff for these.

``lint``
^^^^^^^^

Lint one or more paths, and print a list of lint errors. If "-" is given as the
first path, then the second given path will be used for configuration lookup
and error messages, and the input read from STDIN. No other path may follow,
and "-" after another path is a usage error.

.. code:: console

    $ fixit lint [--diff] [PATH ...]

.. attribute:: --diff / -d

    Show suggested fixes, in unified diff format, when available.

The exit code is 0 when no file has a lint error, 1 when a file has one, and 2
when Fixit could not lint a file (a syntax error, an exception in a rule, or a
configuration of the file that Fixit cannot use); 3 for both.


``fix``
^^^^^^^

Lint one or more paths, and apply suggested fixes. If "-" is given as the
first path, then the second given path will be used for configuration lookup,
the input read from STDIN, and the fixed output printed to STDOUT (ignoring
:attr:`--interactive`). As with ``lint``, no other path may follow.

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

    $ fixit lsp [--stdio | --tcp PORT | --ws PORT]

.. attribute:: --stdio

    Serve LSP over stdio. *default*

.. attribute:: --tcp

    Serve LSP over TCP on PORT.

.. attribute:: --ws

    Serve LSP over WebSocket on PORT.

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
