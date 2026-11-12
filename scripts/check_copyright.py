# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import sys
from collections.abc import Iterable
from pathlib import Path
from subprocess import run

# Use the copyright header from this file as the benchmark for all files
EXPECTED_HEADER = "\n".join(
    line for line in Path(__file__).read_text().splitlines()[:4]
)


def tracked_files() -> Iterable[Path]:
    proc = run(
        # The git of the developer, from PATH (#130).
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],  # noqa: S607
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    yield from (
        path
        for line in proc.stdout.splitlines()
        if (path := Path(line)) and path.is_file() and path.suffix in (".py", ".sh")
    )


def main():
    # The files given, as the hook of prek.toml gives them (#9), or else every
    # tracked file.
    paths = [Path(arg) for arg in sys.argv[1:]] or tracked_files()
    error = False
    for path in paths:
        if path.suffix not in (".py", ".sh"):
            continue
        content = path.read_text("utf-8")
        if EXPECTED_HEADER not in content:
            print(f"Missing or incomplete copyright in {path}")
            error = True
    sys.exit(1 if error else 0)


if __name__ == "__main__":
    main()
