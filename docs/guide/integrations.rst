.. _integrations:

Integrations
------------

.. _ide_integrations:

IDE
^^^

tukuroi can be used to lint as you type as well as to format files.

To get this functionality, install the ``lsp`` extras (e.g.
``pip install "tukuroi[lsp]"``) then set up an LSP client to launch and connect to
the tukuroi LSP server. See the :ref:`lsp command <lsp_command>` for command
usage details.

The server lints the documents that the client opens as Python (``languageId``
``python``), whatever their suffix, and formats only an open document. It reads
the configuration of a document each time it lints it, so a change to a
configuration needs no restart. A syntax error, an exception in a rule, and a
configuration that tukuroi cannot use are diagnostics too, with the severity
Error: a syntax error where it is, and the others at the start of the document.
The traceback of an exception goes to the log of the client.

The server imports the custom rules that the configuration of each opened file
enables, a file outside the workspace too, with the configurations found from
it as for ``lint`` (see :ref:`configuration`). To open code that you do not
trust, start it with ``tukuroi --no-custom-rules lsp`` (see :ref:`security`). It
imports each module of rules once: after changing a custom rule, restart the
server.

Examples of client setup:

- VSCode:

  - `Generic LSP Client <https://github.com/llllvvuu/vscode-glspc>`_
    (via GitHub; requires configuration)

- Neovim: `nvim-lspconfig <https://github.com/neovim/nvim-lspconfig>`_:

.. code:: lua

      require("lspconfig.configs").tukuroi = {
        default_config = {
          cmd = { "tukuroi", "lsp" },
          filetypes = { "python" },
          root_dir = require("lspconfig").util.root_pattern(
            "pyproject.toml", "setup.py", "requirements.txt", ".git",
          ),
          single_file_support = true,
        },
      }

      lspconfig.tukuroi.setup({})

- `Other IDEs <https://microsoft.github.io/language-server-protocol/implementors/tools/>`_

pre-commit
^^^^^^^^^^

tukuroi can be included as a hook for `pre-commit <https://pre-commit.com>`_,
or for `prek <https://prek.j178.dev>`_, which reads the same configuration.

Once you `install it <https://pre-commit.com/#installation>`_, you can add
tukuroi's pre-commit hook to the ``.pre-commit-config.yaml`` file in
your repository.

- To run lint rules on commit, add:

.. code:: yaml

    repos:
      - repo: https://github.com/Fkinds/tukuroi
        rev: v3.0.0
        hooks:
          - id: tukuroi-lint

- To run lint rules and apply autofixes, add:

.. code:: yaml

    repos:
      - repo: https://github.com/Fkinds/tukuroi
        rev: v3.0.0
        hooks:
          - id: tukuroi-fix

- To apply autofixes on commit, and only show the lints in CI, give each hook
  a stage:

.. code:: yaml

    repos:
      - repo: https://github.com/Fkinds/tukuroi
        rev: v3.0.0
        hooks:
          - id: tukuroi-fix
            stages: [pre-commit]
          - id: tukuroi-lint
            stages: [manual]

In CI, run the hooks with the stage ``manual``:

.. code:: console

    $ pre-commit run --all-files --hook-stage manual

``tukuroi-fix`` shows the lints that it cannot fix too: ``tukuroi-lint`` does
not run on commit, where it would show them again. A hook without ``stages``
runs in both, unless ``default_stages`` leaves ``manual`` out.

The hooks install tukuroi without its extras. With ``formatter = "ruff"`` in
the configuration (see :attr:`formatter`), add ruff to the hook:

.. code:: yaml

          - id: tukuroi-fix
            additional_dependencies: ["ruff"]

To read more about how you can customize your pre-commit configuration,
see the `pre-commit docs <https://pre-commit.com/#pre-commit-configyaml---hooks>`__.

The hooks import the custom rules that the repo's configuration enables, and
pre-commit runs the hooks that the repo defines: only run them on repos that
you trust (see :ref:`security`).


.. _machine_readable_output:

Output for programs
^^^^^^^^^^^^^^^^^^^

Two output formats are for programs to read (see :attr:`output-format`).
They print one document on STDOUT, after all the results, and nothing else:
the errors with their tracebacks, the diffs of ``--diff``, the metrics of
``--print-metrics`` and the prompt of ``fix --interactive`` go to STDERR, with
the summary line. ``fix -``, which prints the fixed source on STDOUT, is a
usage error with them. The paths are relative to the current directory when
they are under it, as in the other formats.

``json`` prints one JSON document (RFC 8259), in ASCII. The lines are counted
from 1, and the columns in characters from 0, as in the other formats. The
lists are sorted by path, and the violations by position:

.. code:: json

    {
      "files": ["broken.py", "t.py"],
      "violations": [
        {
          "path": "t.py",
          "rule": "NoAssertTrueForComparisons",
          "message": "\"assertTrue\" does not compare its arguments, ...",
          "autofixable": true,
          "start": {"line": 1, "column": 0},
          "end": {"line": 1, "column": 21},
          "diff": "--- a/t.py\n+++ b/t.py\n..."
        }
      ],
      "errors": [
        {
          "path": "broken.py",
          "type": "tukuroi.core.source.ParseError",
          "message": "Syntax Error @ 1:5: unmatched ')'",
          "traceback": null,
          "position": {"line": 1, "column": 5}
        }
      ],
      "fixed": [{"path": "t.py", "applied": 1, "remaining": 0}]
    }

- ``files``: each file checked.
- ``violations``: the end is the position after the last character, and
  ``diff`` is the diff of the fix of the violation alone, or ``null``.
- ``errors``: a file that tukuroi could not lint. ``position`` is that of a
  syntax error, or ``null``; ``traceback`` is ``null`` for a syntax error.
- ``fixed``: with ``fix``, the files whose fixes were applied, how many, and
  how many violations are left in each.

``sarif`` prints a log of `SARIF 2.1.0
<https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html>`_, with one
run. Its rules are those that the configuration of the current directory
enables, with those reported, each with its message and its docstring; a
result is a violation, with the level ``warning``; and an error of a file is a
notification of the invocation, which makes it unsuccessful. The columns are
counted in code points, from 1 (``columnKind`` is ``unicodeCodePoints``). The
paths are URIs relative to ``%SRCROOT%``, the current directory.

To see the violations in GitHub code scanning, run ``tukuroi lint`` with
``--output-format sarif`` from the root of the repository, and upload the file
with the action ``github/codeql-action/upload-sarif``. ``lint`` exits with 1
when it finds a violation: the step of the upload needs ``if: always()``.

.. code:: console

    $ tukuroi --output-format sarif lint > tukuroi.sarif


VSCode
^^^^^^
For better integration with Visual Studio Code setting ``output-format`` can be set to ``vscode``.
That way VSCode opens the editor at the right position when clicking on code locations in tukuroi's terminal output.
