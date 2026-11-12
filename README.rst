This is an **unofficial fork** of `Instagram/Fixit
<https://github.com/Instagram/Fixit>`_, the linting framework that Meta
published. It is not affiliated with Meta, nor endorsed by Meta or by the
maintainers of Fixit. This repository is named tukuroi; the package, its
module and its command are still named ``fixit``. Its main differences from
upstream:

- The rules run on a new engine, ``fixit.core``, built on Python's ``ast``
  module in place of LibCST.
- Safer handling of untrusted repositories: ``--no-custom-rules`` keeps Fixit
  from importing any rules but its built-in ones, the search for configurations
  stops at the root of the repository, output templates take only the names of
  their fields, and the LSP server talks over stdio only.
- It supports only the two newest minor versions of CPython: 3.14 and 3.15.

Fixit provides a highly configurable linting framework with support for
auto-fixes, custom "local" lint rules, and hierarchical configuration, built
on Python's ``ast`` module, with fixed files formatted by
`ruff <https://docs.astral.sh/ruff/>`_.

Fixit makes it quick and easy to write new lint rules and offer suggested
changes for any errors found, which can then be accepted automatically,
or presented to the user for consideration.

For more details, see the `user guide`__ in ``docs/``.

.. __: https://github.com/Fkinds/tukuroi/tree/main/docs/guide

.. QUICKSTART


License
-------

Fixit is `MIT licensed`__, as found in the LICENSE file.

.. __: https://github.com/Fkinds/tukuroi/blob/main/LICENSE
