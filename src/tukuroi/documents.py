# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The output formats for programs to read (#178): ``json``, one JSON document
(RFC 8259) of the results, and ``sarif``, a log of SARIF 2.1.0, which GitHub
code scanning reads. Each keeps the results, and prints the document at the
end. They are ``MACHINE_READABLE``: tukuroi prints nothing else on the
standard output.
"""

import inspect
import json
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import quote

from .__version__ import __version__
from .config import ConfigError, load_rules
from .core.rule import Rule
from .core.text import Position, Range
from .ftypes import Config, Error, Result, Violation
from .output import shown

SARIF_SCHEMA = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/"
    "sarif-schema-2.1.0.json"
)
INFORMATION_URI = "https://fkinds.github.io/tukuroi/"
# The base of the relative URIs: the current directory.
SRCROOT = "%SRCROOT%"


def _path(path: Path) -> str:
    """``path`` as the other output formats show it."""
    return str(shown(path))


def _position(position: Position) -> dict[str, int]:
    return {"line": position.line, "column": position.column}


class _Document:
    """The results of a run, kept to print them in one document at the end."""

    MACHINE_READABLE: ClassVar[bool] = True

    def __init__(self, config: Config) -> None:
        self.config = config
        self.files: set[str] = set()
        self.violations: list[tuple[str, Violation]] = []
        self.errors: list[tuple[str, Error]] = []
        # The paths of the fixed files, with how many fixes were applied, and
        # how many violations are left.
        self.fixed: list[tuple[str, int, int]] = []

    def start(self) -> str | None:
        return None

    def result(self, result: Result) -> str | None:
        path = _path(result.path)
        self.files.add(path)
        if result.violation is not None:
            self.violations.append((path, result.violation))
        if result.error is not None:
            self.errors.append((path, result.error))
        if result.applied:
            self.fixed.append((path, result.applied, result.remaining))
        return None

    def end(self) -> str | None:
        # ASCII only, which UTF-8 is too, whatever the encoding of the output.
        return json.dumps(self.document(), indent=2)

    def document(self) -> dict[str, Any]:
        raise AssertionError("each output format of a document defines document()")

    def sorted_violations(self) -> list[tuple[str, Violation]]:
        """The violations by path, position and rule: the same for each run."""

        def key(item: tuple[str, Violation]) -> tuple[str, Range, str, str]:
            path, violation = item
            return (path, violation.range, violation.rule_name, violation.message)

        return sorted(self.violations, key=key)

    def sorted_errors(self) -> list[tuple[str, Error]]:
        return sorted(self.errors, key=lambda item: item[0])


class JsonFormat(_Document):
    """
    One JSON document: the files checked, the violations, the errors, and the
    files fixed. The lines are counted from 1, and the columns in characters
    from 0, as with the other output formats.
    """

    def document(self) -> dict[str, Any]:
        return {
            "files": sorted(self.files),
            "violations": [
                {
                    "path": path,
                    "rule": violation.rule_name,
                    "message": violation.message,
                    "autofixable": violation.autofixable,
                    "start": _position(violation.range.start),
                    "end": _position(violation.range.end),
                    "diff": violation.diff or None,
                }
                for path, violation in self.sorted_violations()
            ],
            "errors": [
                {
                    "path": path,
                    "type": error.type,
                    "message": error.message,
                    "traceback": error.traceback or None,
                    "position": None
                    if error.position is None
                    else _position(error.position),
                }
                for path, error in self.sorted_errors()
            ],
            "fixed": [
                {"path": path, "applied": applied, "remaining": remaining}
                for path, applied, remaining in sorted(self.fixed)
            ],
        }


def _region(start: Position, end: Position | None = None) -> dict[str, int]:
    """A region of SARIF: the columns from 1, the end one after the last."""
    region = {"startLine": start.line, "startColumn": start.column + 1}
    if end is not None:
        region |= {"endLine": end.line, "endColumn": end.column + 1}
    return region


def _location(path: str, region: dict[str, int] | None) -> dict[str, Any]:
    """
    A location of SARIF: a URI relative to the current directory, or the
    absolute URI of a file outside it.
    """
    where = Path(path)
    artifact = (
        {"uri": where.as_uri()}
        if where.is_absolute()
        else {"uri": quote(where.as_posix()), "uriBaseId": SRCROOT}
    )
    physical: dict[str, Any] = {"artifactLocation": artifact}
    if region is not None:
        physical["region"] = region
    return {"physicalLocation": physical}


def _descriptor(name: str, rule: type[Rule] | None) -> dict[str, Any]:
    """
    The rule ``name`` for SARIF: its message as the short description, and its
    docstring as the full one and the help. A rule that tukuroi cannot load has
    its name only.
    """
    doc = inspect.cleandoc(rule.__doc__ or "") if rule else ""
    first = " ".join(doc.partition("\n\n")[0].split())
    short = (rule.MESSAGE if rule else "") or first or name
    return {
        "id": name,
        "shortDescription": {"text": short},
        "fullDescription": {"text": doc or short},
        "help": {"text": doc or short},
    }


class SarifFormat(_Document):
    """
    A log of SARIF 2.1.0, with one run: the rules that the config of the current
    directory enables, and those reported; a result for each violation; and a
    notification for each error, which makes the run unsuccessful. The columns
    are counted in code points, from 1.
    """

    def rules(self) -> dict[str, type[Rule] | None]:
        """The rules of the run by name, sorted: those enabled, and those reported."""
        try:
            enabled = load_rules(self.config)
        except ConfigError:
            # Each file has the error as its result.
            enabled = ()
        found: dict[str, type[Rule] | None] = {rule.name(): rule for rule in enabled}
        for _, violation in self.violations:
            found.setdefault(violation.rule_name, None)
        return dict(sorted(found.items()))

    def document(self) -> dict[str, Any]:
        rules = self.rules()
        index = {name: i for i, name in enumerate(rules)}
        results = [
            {
                "ruleId": violation.rule_name,
                "ruleIndex": index[violation.rule_name],
                "level": "warning",
                "message": {"text": violation.message},
                "locations": [
                    _location(path, _region(violation.range.start, violation.range.end))
                ],
            }
            for path, violation in self.sorted_violations()
        ]
        notifications = [
            {
                "level": "error",
                "message": {"text": f"{error.type}: {error.message}"},
                "locations": [
                    _location(
                        path,
                        None if error.position is None else _region(error.position),
                    )
                ],
                "exception": {"kind": error.type, "message": error.message},
            }
            for path, error in self.sorted_errors()
        ]
        driver = {
            "name": "tukuroi",
            "version": __version__,
            "informationUri": INFORMATION_URI,
            "rules": [_descriptor(name, rule) for name, rule in rules.items()],
        }
        run = {
            "tool": {"driver": driver},
            "invocations": [
                {
                    "executionSuccessful": not notifications,
                    "toolExecutionNotifications": notifications,
                }
            ],
            "originalUriBaseIds": {SRCROOT: {"uri": Path.cwd().as_uri() + "/"}},
            "columnKind": "unicodeCodePoints",
            "results": results,
        }
        return {"$schema": SARIF_SCHEMA, "version": "2.1.0", "runs": [run]}
