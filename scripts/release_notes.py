# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The notes of a release: the section of its tag in the changelog.

    python scripts/release_notes.py v3.0.0 [CHANGELOG.md]

It prints the section under the heading of the tag (``## v3.0.0`` or
``## 3.0.0``, with a date after it or not), without the heading, up to the
next heading of the same level. release.yml makes it the body of the GitHub
release. A tag without a section, or with an empty one, exits with 1.
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).parent.parent / "CHANGELOG.md"


def notes(tag: str, changelog: str) -> str | None:
    """The section of ``tag`` in ``changelog``, or None if there is none."""
    version = re.escape(tag.removeprefix("v"))
    heading = re.compile(rf"^## v?{version}(?:\s.*)?$")
    found: list[str] | None = None
    for line in changelog.splitlines():
        if found is None:
            if heading.match(line):
                found = []
        elif line.startswith("## "):
            break
        else:
            found.append(line)
    text = "\n".join(found or []).strip()
    return text or None


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(f"usage: {argv[0]} TAG [CHANGELOG]", file=sys.stderr)
        return 2
    path = Path(argv[2]) if len(argv) == 3 else CHANGELOG
    text = notes(argv[1], path.read_text())
    if text is None:
        print(f"{path}: no notes for {argv[1]}", file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
