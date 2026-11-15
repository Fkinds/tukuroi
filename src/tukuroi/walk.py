# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The Python files of a directory (#197), as trailrunner found them before:
those of the ``.gitignore`` at the root of the project left out, as git reads
it (:class:`pathspec.GitIgnoreSpec`).
"""

from collections.abc import Iterator
from pathlib import Path

from pathspec import GitIgnoreSpec

# What marks the root of a project, in it.
ROOT_MARKERS = ("pyproject.toml", ".git", ".hg")
SUFFIXES = (".py", ".pyi")


def project_root(path: Path) -> Path:
    """
    The root of the project of ``path``: the nearest directory with one of
    :data:`ROOT_MARKERS`, from ``path`` up, or else the root of the file system.
    """
    path = path.resolve()
    for parent in (path, *path.parents):
        if any((parent / marker).exists() for marker in ROOT_MARKERS):
            return parent
    return Path(path.anchor)


def gitignore(root: Path) -> GitIgnoreSpec:
    """The patterns of the ``.gitignore`` in ``root``: none without one."""
    file = root / ".gitignore"
    lines = file.read_text(encoding="utf-8").splitlines() if file.is_file() else []
    return GitIgnoreSpec.from_lines(lines)


def walk(directory: Path) -> Iterator[Path]:
    """
    The files of ``directory`` with a suffix of :data:`SUFFIXES`, and those of
    its directories, by name, but those that the ``.gitignore`` at the root of
    the project has, or that are in a directory that it has. ``directory``
    itself may be one. Each path starts with ``directory``.

    A symbolic link to a file is a file, and one to a directory is not walked:
    git keeps the link, not what it points to, and the walk does not leave the
    project, nor go round a loop.
    """
    root = project_root(directory)
    ignored = gitignore(root)
    # Where ``directory`` is in the project: the paths under it, as they are
    # written, without resolving their links.
    base = directory.resolve().relative_to(root)
    if base != Path() and ignored.match_file(f"{base.as_posix()}/"):
        return
    yield from _files(directory, base, ignored)


def _files(directory: Path, base: Path, ignored: GitIgnoreSpec) -> Iterator[Path]:
    for child in sorted(directory.iterdir()):
        where = (base / child.name).as_posix()
        if child.is_dir() and not child.is_symlink():
            if not ignored.match_file(f"{where}/"):
                yield from _files(child, base / child.name, ignored)
        elif (
            child.suffix in SUFFIXES
            and child.is_file()
            and not ignored.match_file(where)
        ):
            yield child
