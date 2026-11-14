# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Tests of scripts/release_notes.py: the notes of a release, from the changelog."""

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import release_notes

CHANGELOG = """\
# Changelog

## v3.1.0 (2026-12-01)

### Feat

- **cli**: something new

## v3.0.0 (2026-11-20)

### BREAKING CHANGE

- the name is tukuroi

### Fix

- **api**: something fixed

## 3.0.0rc1

- a candidate

## v2.9.0 (2026-01-01)

## v2.2.1 (2025-06-01)

- upstream
"""


class NotesTest(TestCase):
    def test_section(self) -> None:
        cases = (
            # (tag, notes)
            ("v3.1.0", "### Feat\n\n- **cli**: something new"),
            ("v3.0.0", "### BREAKING CHANGE\n\n- the name is tukuroi\n\n### Fix\n\n- **api**: something fixed"),
            # A heading without "v", and without a date.
            ("v3.0.0rc1", "- a candidate"),
            # The last section, up to the end.
            ("v2.2.1", "- upstream"),
            # An empty section, and none: no notes.
            ("v2.9.0", None),
            ("v4.0.0", None),
            # The version is not a pattern, nor a prefix of another.
            ("v3.0", None),
            ("v3x1x0", None),
        )  # fmt: skip
        for tag, expected in cases:
            with self.subTest(tag):
                self.assertEqual(release_notes.notes(tag, CHANGELOG), expected)


class MainTest(TestCase):
    def run_main(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "CHANGELOG.md"
            path.write_text(CHANGELOG)
            argv = [arg.replace("CHANGELOG", str(path)) for arg in args]
            with redirect_stdout(out), redirect_stderr(err):
                code = release_notes.main(["release_notes.py", *argv])
        return code, out.getvalue(), err.getvalue().replace(str(path), "PATH")

    def test_prints_the_notes(self) -> None:
        code, out, err = self.run_main("v2.2.1", "CHANGELOG")
        self.assertEqual((code, out, err), (0, "- upstream\n", ""))

    def test_no_notes(self) -> None:
        code, out, err = self.run_main("v4.0.0", "CHANGELOG")
        self.assertEqual((code, out, err), (1, "", "PATH: no notes for v4.0.0\n"))

    def test_usage(self) -> None:
        code, out, err = self.run_main()
        self.assertEqual((code, out), (2, ""))
        self.assertEqual(err, "usage: release_notes.py TAG [CHANGELOG]\n")

    def test_changelog_of_the_repository(self) -> None:
        # By default, CHANGELOG.md at the top of the repository.
        top = Path(__file__).resolve().parents[2]
        self.assertEqual(release_notes.CHANGELOG.resolve(), top / "CHANGELOG.md")
