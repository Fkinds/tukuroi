# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Tests of ``tukuroi.core.imports``. The cases are decision tables (ISO/IEC/IEEE
29119-4) of how a module is already imported (not at all, the same name, the
module, an alias, another thing with the name), and of the shapes of a module
where the import goes (empty, comments, a docstring, imports, code, line ends).
"""

from unittest import TestCase

from ..core.edits import apply_fixes
from ..core.imports import add_import
from ..core.names import ImportTable
from ..core.source import Source


def added(text: str, module: str, name: str | None = None) -> tuple[str, str] | None:
    """The name to use, and the text with the import added, or ``None``."""
    source = Source.from_text(text)
    result = add_import(source, ImportTable.from_tree(source.tree), module, name)
    if result is None:
        return None
    fixes = [[result.edit]] if result.edit else []
    return result.name, apply_fixes(text, fixes).text


class AddImportTest(TestCase):
    def test_already_imported(self) -> None:
        cases = (
            # (label, text, module, name, the name to use)
            ("the same", "from dataclasses import dataclass\n", "dataclasses", "dataclass", "dataclass"),
            ("an alias", "from dataclasses import dataclass as dc\n", "dataclasses", "dataclass", "dc"),
            ("the module", "import dataclasses\n", "dataclasses", "dataclass", "dataclasses.dataclass"),
            ("the module, alias", "import dataclasses as d\n", "dataclasses", "dataclass", "d.dataclass"),
            ("import, the same", "import os\n", "os", None, "os"),
            ("import, an alias", "import os as o\n", "os", None, "o"),
            ("in a function", "def f():\n    from dataclasses import dataclass\n", "dataclasses", "dataclass", "dataclass"),
        )  # fmt: skip
        for label, text, module, name, use in cases:
            with self.subTest(label):
                self.assertEqual(added(text, module, name), (use, text))

    def test_clash(self) -> None:
        cases = (
            # (label, text, module, name)
            ("another import of the name", "from attrs import dataclass\n", "dataclasses", "dataclass"),
            ("a class of the name", "class dataclass:\n    pass\n", "dataclasses", "dataclass"),
            ("a function of the name", "def dataclass():\n    pass\n", "dataclasses", "dataclass"),
            ("a variable of the name", "dataclass = 1\n", "dataclasses", "dataclass"),
            ("an annotated variable", "dataclass: int = 1\n", "dataclasses", "dataclass"),
            ("in a tuple target", "a, dataclass = 1, 2\n", "dataclasses", "dataclass"),
            ("import, another module", "import other as os\n", "os", None),
            ("import, a variable", "os = 1\n", "os", None),
        )  # fmt: skip
        for label, text, module, name in cases:
            with self.subTest(label):
                self.assertIsNone(added(text, module, name))

    def test_where_it_goes(self) -> None:
        line = "from dataclasses import dataclass"
        cases = (
            # (label, text, text with the import)
            ("empty", "", f"{line}\n"),
            ("a comment", "# c\n", f"# c\n{line}\n"),
            ("a comment, no line end", "# c", f"# c\n{line}\n"),
            ("code", "x = 1\n", f"{line}\nx = 1\n"),
            ("comments, then code", "#!/x\n# c\n\nx = 1\n", f"#!/x\n# c\n\n{line}\nx = 1\n"),
            ("a decorated class", "# c\n@d\nclass C:\n    pass\n", f"# c\n{line}\n@d\nclass C:\n    pass\n"),
            ("a docstring", '"""doc"""\nx = 1\n', f'"""doc"""\n{line}\nx = 1\n'),
            ("a docstring, then imports", '"""doc"""\nimport os\n\nx = 1\n', f'"""doc"""\nimport os\n{line}\n\nx = 1\n'),
            ("imports", "import os\nimport sys\n\nx = 1\n", f"import os\nimport sys\n{line}\n\nx = 1\n"),
            ("__future__", "from __future__ import annotations\nx = 1\n", f"from __future__ import annotations\n{line}\nx = 1\n"),
            ("an import on 2 lines", "from os import (\n    path,\n)\nx = 1\n", f"from os import (\n    path,\n)\n{line}\nx = 1\n"),
            ("an import, then a comment", "import os  # c\nx = 1\n", f"import os  # c\n{line}\nx = 1\n"),
            ("imports after code", "x = 1\nimport os\n", f"{line}\nx = 1\nimport os\n"),
            ("the last line, no line end", "import os", f"import os\n{line}\n"),
            ("\\r\\n", "import os\r\nx = 1\r\n", f"import os\r\n{line}\r\nx = 1\r\n"),
            ("\\r", "import os\rx = 1\r", f"import os\r{line}\rx = 1\r"),
        )  # fmt: skip
        for label, text, result in cases:
            with self.subTest(label):
                self.assertEqual(
                    added(text, "dataclasses", "dataclass"), ("dataclass", result)
                )

    def test_import_module(self) -> None:
        cases = (
            # (label, text, module, name to use, text with the import)
            ("a module", "x = 1\n", "os", "os", "import os\nx = 1\n"),
            ("a dotted module", "x = 1\n", "os.path", "os.path", "import os.path\nx = 1\n"),
            ("next to its package", "import os\n", "os.path", "os.path", "import os\nimport os.path\n"),
        )  # fmt: skip
        for label, text, module, use, result in cases:
            with self.subTest(label):
                self.assertEqual(added(text, module), (use, result))
