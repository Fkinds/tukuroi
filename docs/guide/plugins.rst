.. _plugins:

Plugins
-------

Other packages add to tukuroi: rules, formatters, and output formats. A
package that you install with tukuroi brings them; a configuration of the
repository names them. They run the code of the package: with custom rules turned off (see
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

Output formats
^^^^^^^^^^^^^^

An output format prints the results of ``tukuroi lint`` and ``tukuroi fix``,
when a configuration names it with :attr:`output-format`, or the command line
with ``--output-format``. It is a class with the methods of
:class:`tukuroi.OutputFormatPlugin`, that a package registers in the entry
points ``tukuroi.output_formats``:

.. code:: python

    # tukuroi_count/__init__.py

    from tukuroi import Config, Result


    class CountFormat:
        def __init__(self, config: Config) -> None:
            self.count = 0

        def start(self) -> str | None:
            return None

        def result(self, result: Result) -> str | None:
            if result.violation is None:
                return None
            self.count += 1
            line = result.violation.range.start.line
            return f"{result.path}:{line} {result.violation.message}"

        def end(self) -> str | None:
            return f"{self.count} violations"

.. code:: toml

    # pyproject.toml of tukuroi-count

    [project.entry-points."tukuroi.output_formats"]
    count = "tukuroi_count:CountFormat"

tukuroi makes the class once for a run, with the configuration of the current
directory, and prints what ``start`` gives before the results, what ``result``
gives for each :class:`~tukuroi.Result`, and what ``end`` gives after them;
``None`` prints nothing. tukuroi itself still prints an error with its
traceback, and the diff of a fix with ``--diff``. ``tukuroi fix -`` prints the
fixed source alone on the standard output, and all of this on the standard
error. The names are in any letter case. ``fixit``, ``vscode``, ``custom``,
``json`` and ``sarif`` come with tukuroi, registered the same way. With custom
rules turned off, tukuroi prints ``fixit`` in place of another, with a warning.

A format for programs to read sets the class attribute
``MACHINE_READABLE = True``, as ``json`` and ``sarif`` do. tukuroi then prints
what the format gives without colors, alone on the standard output, and the
rest on the standard error (see :ref:`machine_readable_output`). Without the
attribute, a format is for people to read.
