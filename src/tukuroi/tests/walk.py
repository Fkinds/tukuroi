# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The Python files of a directory (#197): the root of the project, its
``.gitignore`` as git reads it, the order, and the symbolic links.
"""

from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from .. import walk as walk_module
from ..util import chdir
from ..walk import gitignore, project_root, walk

TREE = {
    "repo/pyproject.toml": "",
    "repo/.gitignore": "ign.py\nbuild/\n!build/y.py\n*.tmp.py\n!keep.tmp.py\n/top.py\n",
    "repo/b.py": "",
    "repo/a.pyi": "",
    "repo/c.txt": "",
    "repo/top.py": "",
    "repo/x.tmp.py": "",
    "repo/keep.tmp.py": "",
    "repo/pkg/ign.py": "",
    "repo/pkg/m.py": "",
    "repo/pkg/top.py": "",
    "repo/pkg/build/x.py": "",
    "repo/build/y.py": "",
    "repo/sub/.gitignore": "m.py\n",
    "repo/sub/m.py": "",
    "outside/o.py": "",
}


@contextmanager
def tree(files: Mapping[str, str] = TREE) -> Generator[Path]:
    """``files`` in a new directory, which is the current one."""
    with TemporaryDirectory() as td:
        root = Path(td).resolve()
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        with chdir(root):
            yield root


def names(paths: list[Path]) -> list[str]:
    return [path.as_posix() for path in paths]


class WalkTest(TestCase):
    maxDiff = None

    def test_gitignore_of_the_root(self) -> None:
        # By name, in each directory; only the .gitignore of the root, as git
        # reads it: a directory, a pattern from the root, and a negation, but
        # in a directory left out (pathspec alone takes back build/y.py).
        with tree():
            found = names(list(walk(Path("repo"))))
        expected = [
            "repo/a.pyi",
            "repo/b.py",
            "repo/keep.tmp.py",
            "repo/pkg/m.py",
            "repo/pkg/top.py",
            "repo/sub/m.py",
        ]
        self.assertEqual(found, expected)

    def test_from_a_directory_of_the_project(self) -> None:
        # The paths start with the one given, and are matched from the root.
        cases = (
            # (directory, cwd, files)
            ("pkg", "repo", ["pkg/m.py", "pkg/top.py"]),
            ("./pkg", "repo", ["pkg/m.py", "pkg/top.py"]),
            (".", "repo/pkg", ["m.py", "top.py"]),
            ("../pkg", "repo/sub", ["../pkg/m.py", "../pkg/top.py"]),
            # A directory that .gitignore has: none.
            ("build", "repo", []),
            ("pkg/build", "repo", []),
        )
        for directory, cwd, expected in cases:
            with self.subTest(directory, cwd=cwd), tree() as root, chdir(root / cwd):
                self.assertEqual(names(list(walk(Path(directory)))), expected)

    def test_symbolic_links(self) -> None:
        # A link to a file is a file; one to a directory is not walked, out of
        # the project or not, nor round a loop.
        with tree() as root:
            repo = root / "repo"
            (repo / "link.py").symlink_to(root / "outside/o.py")
            (repo / "out").symlink_to(root / "outside")
            (repo / "pkg/loop").symlink_to(repo)
            (repo / "broken.py").symlink_to(root / "nothing.py")
            found = names(list(walk(Path("repo"))))
            # Given by name, a link to a directory is walked, from where it
            # points.
            given = names(list(walk(Path("repo/out"))))
        self.assertIn("repo/link.py", found)
        self.assertFalse([name for name in found if "out/" in name or "loop" in name])
        self.assertNotIn("repo/broken.py", found)
        self.assertEqual(given, ["repo/out/o.py"])

    def test_project_root(self) -> None:
        files = {
            "a/pyproject.toml": "",
            "a/b/c/t.py": "",
            "g/.git/HEAD": "",
            "g/d/t.py": "",
            "h/.hg/store": "",
        }
        with tree(files) as root:
            cases = (
                ("a/b/c/t.py", "a"),
                ("a/b/c", "a"),
                ("a", "a"),
                ("g/d", "g"),
                ("h", "h"),
            )
            for path, expected in cases:
                with self.subTest(path):
                    self.assertEqual(project_root(Path(path)), root / expected)
            # No marker up to the root of the file system: that root.
            with patch.object(walk_module, "ROOT_MARKERS", ("no-such-marker",)):
                self.assertEqual(project_root(Path("a")), Path(root.anchor))

    def test_gitignore(self) -> None:
        with tree({"pyproject.toml": "", ".gitignore": "é.py\n"}) as root:
            self.assertTrue(gitignore(root).match_file("é.py"))
            # None in the directory: nothing is left out.
            self.assertFalse(gitignore(root / "nowhere").match_file("a.py"))
