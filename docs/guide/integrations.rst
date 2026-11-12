.. _integrations:

Integrations
------------

.. _ide_integrations:

IDE
^^^

Fixit can be used to lint as you type as well as to format files.

To get this functionality, install the ``lsp`` extras (e.g.
``pip install "fixit[lsp]"``) then set up an LSP client to launch and connect to
the Fixit LSP server. See the :ref:`lsp command <lsp_command>` for command
usage details.

The server lints the documents that the client opens as Python (``languageId``
``python``), whatever their suffix, and formats only an open document. It reads
the configuration of a document each time it lints it, so a change to a
configuration needs no restart. A syntax error, an exception in a rule, and a
configuration that Fixit cannot use are diagnostics too, with the severity
Error: a syntax error where it is, and the others at the start of the document.
The traceback of an exception goes to the log of the client.

The server imports the custom rules that the configuration of each opened file
enables, a file outside the workspace too, with the configurations found from
it as for ``lint`` (see :ref:`configuration`). To open code that you do not
trust, start it with ``fixit --no-custom-rules lsp`` (see :ref:`security`). It
imports each module of rules once: after changing a custom rule, restart the
server.

Examples of client setup:

- VSCode:

  - `Generic LSP Client <https://github.com/llllvvuu/vscode-glspc>`_
    (via GitHub; requires configuration)
  - `Fixit (Unofficial) <https://marketplace.visualstudio.com/items?itemName=llllvvuu.fixit-unofficial>`_
    (via VSCode Marketplace; compiled from Generic LSP Client with preset
    configuration for Fixit)

- Neovim: `nvim-lspconfig <https://github.com/neovim/nvim-lspconfig>`_:

.. code:: lua

      require("lspconfig.configs").fixit = {
        default_config = {
          cmd = { "fixit", "lsp" },
          filetypes = { "python" },
          root_dir = require("lspconfig").util.root_pattern(
            "pyproject.toml", "setup.py", "requirements.txt", ".git",
          ),
          single_file_support = true,
        },
      }

      lspconfig.fixit.setup({})

- `Other IDEs <https://microsoft.github.io/language-server-protocol/implementors/tools/>`_

pre-commit
^^^^^^^^^^

Fixit can be included as a hook for `pre-commit <https://pre-commit.com>`_,
or for `prek <https://prek.j178.dev>`_, which reads the same configuration.

Once you `install it <https://pre-commit.com/#installation>`_, you can add
Fixit's pre-commit hook to the ``.pre-commit-config.yaml`` file in
your repository.

- To run lint rules on commit, add:

.. code:: yaml

    repos:
      - repo: https://github.com/Fkinds/tukuroi
        rev: <commit SHA>  # no release of this fork has a tag yet
        hooks:
          - id: fixit-lint

- To run lint rules and apply autofixes, add:

.. code:: yaml

    repos:
      - repo: https://github.com/Fkinds/tukuroi
        rev: <commit SHA>  # no release of this fork has a tag yet
        hooks:
          - id: fixit-fix

To read more about how you can customize your pre-commit configuration,
see the `pre-commit docs <https://pre-commit.com/#pre-commit-configyaml---hooks>`__.

The hooks import the custom rules that the repo's configuration enables, and
pre-commit runs the hooks that the repo defines: only run them on repos that
you trust (see :ref:`security`).


VSCode
^^^^^^
For better integration with Visual Studio Code setting ``output-format`` can be set to ``vscode``.
That way VSCode opens the editor at the right position when clicking on code locations in Fixit's terminal output.
