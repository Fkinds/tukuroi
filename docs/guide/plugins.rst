.. _plugins:

Plugins
-------

Other packages add to tukuroi: rules, and formatters. A package that you
install with tukuroi brings them; a configuration of the repository names
them. They run the code of the package: with custom rules turned off (see
:ref:`security`), tukuroi uses only those that come with it.

Rules
^^^^^

A package of rules needs nothing more than its modules: the configuration
names them, as it names the rules in the repository (see :ref:`writing-rules`),
without the leading ``.``:

.. code:: toml

    [tool.tukuroi]
    enable = ["tukuroi_django.rules"]

Formatters
^^^^^^^^^^

A formatter formats the files that ``tukuroi fix`` fixes, when a configuration
names it with :attr:`formatter`. It is a class with two methods, as
:class:`tukuroi.FormatterPlugin` has them, that a package registers in the
entry points ``tukuroi.formatters``, by the name that the configuration gives:

.. code:: python

    # tukuroi_black/__init__.py

    import importlib.util
    from pathlib import Path


    class BlackFormatter:
        def available(self) -> str | None:
            # Why it cannot run, or None.
            if importlib.util.find_spec("black") is None:
                return "needs the black package"
            return None

        def format(self, text: str, path: Path | None) -> str:
            import black

            return black.format_str(text, mode=black.Mode())

.. code:: toml

    # pyproject.toml of tukuroi-black

    [project.entry-points."tukuroi.formatters"]
    black = "tukuroi_black:BlackFormatter"

tukuroi makes the class with no argument, and calls ``format`` with the fixed
text of a file and its path, or ``None`` for the standard input. ``ruff``
comes with tukuroi, registered the same way. When two packages register a
name, that of tukuroi wins.
