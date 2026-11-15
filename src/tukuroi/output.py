# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The output formats of ``lint`` and ``fix`` (#169): plugins registered in the
entry points ``tukuroi.output_formats``, by the name that ``output-format`` of
a config, or ``--output-format``, gives. tukuroi registers its own the same
way: ``tukuroi``, ``vscode`` and ``custom``, and ``json`` and ``sarif`` of
:mod:`tukuroi.documents` (#178).
"""

from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

from .ftypes import Config, Result
from .template import format_template


@runtime_checkable
class OutputFormatPlugin(Protocol):
    """
    An output format: a class registered in the entry points
    ``tukuroi.output_formats``. tukuroi makes one for a run, with the config of
    the run (such as its ``output_template``), and prints what it gives: at
    the start, for each result, and at the end. ``None`` prints nothing.

    A format for programs to read, such as one JSON document, sets the class
    attribute ``MACHINE_READABLE = True`` (#178). tukuroi then prints on the
    standard output what the format gives, without colors, and nothing else:
    an error with its traceback, the diff of a fix, the metrics and the prompt
    of ``fix`` go to the standard error, and ``fix -``, whose standard output is
    the fixed source, is a usage error. Without the attribute, the format is
    for people to read.
    """

    def __init__(self, config: Config) -> None: ...

    def start(self) -> str | None:
        """What to print before the results, such as the start of a document."""
        ...

    def result(self, result: Result) -> str | None:
        """What to print for ``result``: a violation, an error, or a clean file."""
        ...

    def end(self) -> str | None:
        """What to print after the results, such as the end of a document."""
        ...


def machine_readable(output: OutputFormatPlugin | None) -> bool:
    """Whether ``output`` is a format for programs to read: ``MACHINE_READABLE``."""
    return getattr(output, "MACHINE_READABLE", False) is True


def shown(path: Path) -> Path:
    """``path`` relative to the current directory, if it is under it."""
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


class _Lines:
    """An output format of a line for each violation, and nothing else."""

    TEMPLATE: ClassVar[str] = ""

    def __init__(self, config: Config) -> None:
        self.config = config

    def start(self) -> str | None:
        return None

    def result(self, result: Result) -> str | None:
        if result.violation is None:
            return None
        violation = result.violation
        message = violation.message
        if violation.autofixable:
            message += " (has autofix)"
        start, end = violation.range.start, violation.range.end
        # The names only, and strings and numbers (#14).
        values: dict[str, str | int] = {
            "end_col": end.column,
            "end_line": end.line,
            "message": message,
            "path": str(shown(result.path)),
            "rule_name": violation.rule_name,
            "start_col": start.column,
            "start_line": start.line,
        }
        return format_template(self.template(), values)

    def end(self) -> str | None:
        return None

    def template(self) -> str:
        return self.TEMPLATE


class TukuroiFormat(_Lines):
    """``path@line:column rule: message``: the default."""

    TEMPLATE = "{path}@{start_line}:{start_col} {rule_name}: {message}"


class VscodeFormat(_Lines):
    """``path:line:column rule: message``, which VS Code opens at the line."""

    TEMPLATE = "{path}:{start_line}:{start_col} {rule_name}: {message}"


class CustomFormat(_Lines):
    """The ``output-template`` of the config."""

    def template(self) -> str:
        return self.config.output_template
