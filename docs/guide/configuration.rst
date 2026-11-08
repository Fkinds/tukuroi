.. _configuration:

Configuration
-------------

Fixit uses `TOML format <https://toml.io>`_ for configuration, and supports
hierarchical, cascading configuration. Fixit will read values from both the
standardized ``pyproject.toml`` file as well as a separate ``.fixit.toml`` or
``fixit.toml`` file, with values from the latter taking precendence over the
former, and values from files "nearer" to those being linted taking precedence
over values from files "further" away.

When determining the configuration to use for a given path, Fixit will continue
looking upward in the filesystem until it reaches either the root of the
filesystem, or a configuration file is found with :attr:`root` set to ``True``.
Fixit will then read configuration values from each file, from further to
nearest, and merge or override values as appropriate.

This behavior enables a monorepo to provide a baseline configuration, while
individual projects can choose to either add to that baseline, or define their
own root of configuration to ignore any other baseline configs. This also allows
the inclusion of external or third-party projects to maintain consistent linting
results, regardless of whether they are being linted externally or within the
containing monorepo.


``[tool.fixit]``
^^^^^^^^^^^^^^^^

The main configuration table.

.. attribute:: root
    :type: bool
    :value: false

    Marks this file as a root of the configuration hierarchy.

    If set to ``true``, Fixit will not visit any configuration files further up
    the filesystem hierarchy.

.. attribute:: enable
    :type: list[str]
    :value: []

    List of modules or individual rules to enable when linting files covered
    by this configuration.

    Rules bundled with Fixit, or available in the environment's site-packages,
    can be referenced as a group by their fully-qualified package name, or
    individually by adding a colon and the rule name:

    .. code-block:: toml

        enable = [
            "fixit.rules",  # all lint rules in this package (non-recursive)
            "fixit.rules:UseAssertIn",  # single lint rule by name
        ]

    Local rules, available only in the repo being linted, can be referenced by
    their locally-qualified package names, as if they were being imported from
    a Python module *relative to the configuration file specifying the rule*:

    .. code-block:: toml

        # teambread/fixit.toml
        enable = [
            ".rules",  # all rules in teambread/rules/ (non-recursive)
            ".rules.hollywood",  # all rules in teambread/rules/hollywood.py
            ".rules:HollywoodName",  # single lint rule by name
        ]

    Overrides disabled rules from any configuration further up the hierarchy.

    Fixit will enable the built-in :mod:`fixit.rules` lint rules by default.

    Fixit imports the rules that are enabled, which runs their code. See
    :ref:`security` for the configurations to trust, and for turning off the
    rules that do not come with Fixit.

.. attribute:: disable
    :type: list[str]
    :value: []

    List of modules or individual rules to disable when linting files covered
    by this configuration.

    Overrides enabled rules from this file, as well any configuration files
    further up the hierarchy.

    See :attr:`enable` for details on referencing lint rules.

.. attribute:: enable-root-import
    :type: bool | str

    Allow importing local rules using absolute imports, relative to the root
    of the project. This provides an alternative to using dotted rule names for
    enabling and importing local rules (see :attr:`enable`) from either the
    directory containing the root config (when set to ``true``), or a single,
    optional path relative to the root config.

    For example, project ``orange`` using a ``src/orange/`` project hierarchy
    could use the following config:

    .. code-block:: toml

        root = true
        enable-root-import = "src"
        enable = ["orange.rules"]

    Assuming that the namespace ``orange`` is not already in site-packages,
    then ``orange.rules`` would be imported from ``src/orange/rules/``, while
    also allowing these local rules to import from other components in the
    ``orange`` namespace.

    This option may only be specified in the root config file. Specifying the
    option in any other config file is treated as a configuration error.
    Absolute paths, or paths containing ``..`` parent-relative components,
    are not allowed. Any value other than ``true``, ``false``, or a relative
    path that is not empty is a configuration error.

    This option is roughly equivalent to adding the configured path, relative
    to the root configuration, to :attr:`sys.path` when attempting to import
    and materialize any enabled lint rules.

    With custom rules turned off (see :ref:`security`), this option is ignored.

.. attribute:: output-format
    :type: str

    Choose one of the presets for terminal output formatting.
    This option is inferred based on the current working directory or from
    an explicity specified config file -- subpath overrides will be ignored.

    Can be one of:

    - ``custom``: Specify your own format using the :attr:`output-template`
      option below.
    - ``fixit``: Fixit's default output format.
    - ``vscode``: A format that provides clickable paths for Visual Studio Code.

    .. note::

        The default output format is planned to change to ``vscode`` in
        the next feature release, expected as part of ``v2.3`` or ``v3.0``.
        If you are sensitive to output formats changing, specify your preferred
        format in your project configs accordingly.

.. attribute:: output-template
    :type: str

    Sets the format of output printed to terminal.
    Python formatting is used in the background to fill in data.
    Only active with :attr:`output-format` set to ``custom``.

    This option is inferred based on the current working directory or from
    an explicity specified config file -- subpath overrides will be ignored.

    Supported variables:

    - ``message``: Message emitted by the applied rule.

    - ``path``: Path to affected file.

    - ``result``: Raw :class:`~fixit.Result` object.

    - ``rule_name``: Name of the applied rule.

    - ``start_col``: Start column of affected code.

    - ``start_line``: Start line of affected code.


.. _overrides:

``[[tool.fixit.overrides]]``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Overrides provide a mechanism for hierarchical configuration within a single
configuration file. They are defined as an
`array of tables <https://toml.io/en/v1.0.0#array-of-tables>`_, with each table
defining the subpath it applies to, along with any values from the tables above:

.. code-block:: toml

    [[tool.fixit.overrides]]
    path = "foo/bar"
    disable = ["fixit.rules:ExampleRule"]

    [[tool.fixit.overrides]]
    path = "fizz/buzz"
    enable = ["plugin:SomethingNeat"]


.. _security:

Security
^^^^^^^^

Configuration files can run code. Fixit imports the rules that a configuration
enables, which runs their code with the permissions of the user running Fixit.
That includes custom rules: local rules in the repo (see :attr:`enable`), the
modules found through :attr:`enable-root-import`, and rules from any package
other than Fixit. Rules named in :attr:`disable`, and the rules checked by
``fixit validate-config``, are imported too.

Fixit looks for configuration files from each linted file up to the root of the
filesystem (unless a file sets :attr:`root`), so a configuration file in a
parent directory of the repo can also enable rules.

Only run Fixit with custom rules on code whose configuration you trust. For
other code, turn custom rules off with ``--no-custom-rules``, or with the
environment variable ``FIXIT_CUSTOM_RULES=0`` (see :ref:`commands`). Then Fixit
imports only the built-in rules, in :mod:`fixit.rules`:

- Custom rules in :attr:`enable` are skipped with a warning. The built-in rules
  still run, and the exit code does not change.
- Custom rules in :attr:`disable`, and :attr:`enable-root-import`, are ignored.
- ``fixit validate-config`` checks only the names of custom rules, and warns
  that it skipped them.
- A custom rule named with ``--rules``, or given to ``fixit test``, is a usage
  error.

Turn custom rules off when Fixit runs on code that others can change, such as:

- CI jobs that lint pull requests from forks,
- repositories that you clone to review or investigate,
- editors that start ``fixit lsp`` in any folder that you open.

For example, in a CI job:

.. code:: console

    $ FIXIT_CUSTOM_RULES=0 fixit lint src/

To keep custom rules off by default, set ``FIXIT_CUSTOM_RULES=0`` in your
shell, and pass ``--custom-rules`` in the repos that you trust. The option on
the command line wins over the variable. So the variable does not keep custom
rules off when the repo can change the command line, for example with the
``args`` of a hook in ``.pre-commit-config.yaml``, or with the workspace
settings of an editor that starts ``fixit lsp``. pre-commit runs the hooks that
the repo defines, so running it on a repo is beyond what this option can
protect.

Also:

- Run the ``fixit`` command, or ``python -P -m fixit``. ``python -m fixit``
  puts the current directory first on :attr:`sys.path`. Fixit takes it off
  when it starts, so that the modules it imports later (such as a formatter)
  are not read from there. But a ``fixit`` package in the current directory is
  imported in place of Fixit before that.
- To use a configuration that you trust instead of the ones found next to the
  linted files, pass ``--config-file``. Fixit still imports the custom rules
  that it enables.
