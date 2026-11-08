# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Characterization tests for ``fixit lsp`` over stdio: the ``initialize`` result,
the lifecycle and the exit code, ``textDocument/publishDiagnostics`` after
``didOpen`` and ``didChange``, the result of ``textDocument/formatting``, and
the config and the URI of the document.

They run the CLI only, so that the engine rewrite (#21) can be checked against
them. The expected values are copied from the output of the libcst engine.
``NOTE`` marks behavior that looks wrong but is pinned as is. The server runs
the new engine (#21): it counts positions in the encoding agreed with the
client and in the text of the client (LSP 3.17), and runs ``ruff format`` after
a fix.

``invoke`` of ``characterization_cli`` does not fit: on ``exit`` the server
closes stdout, which ``click`` reads afterwards.
"""

import io
import json
import sys
import warnings
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from .. import __version__
from ..cli import main
from ..lsp import BOM
from ..util import chdir
from .characterization_cli import CharacterizationTestCase, config, fresh_logging
from .characterization_fix import ruff_format
from .characterization_suppression import MESSAGES

Json = Any

UI = "UseAssertIn"
NA = "NoAssertTrueForComparisons"
NN = "UseAssertIsNotNone"
SI = "NoStaticIfCondition"
NT = "NoNamedTuple"
SA = "SortedAttributes"
VC = "VariadicCallableSyntax"

CALL = "self.assertTrue(a in b)"  # UI reports it, with an autofix.
FIXED = "self.assertIn(a, b)"
FIXABLE = "self.assertTrue(a, 3)\n"  # NA reports it, with an autofix.
UNFIXABLE = "if True:\n    pass\n"  # SI reports it, without an autofix.
# What NA and SI report in FIXABLE + UNFIXABLE.
NA_0 = (NA, "0:0", "0:21")
SI_1 = (SI, "1:0", "2:8")

# Stands for the temporary directory, in the messages and out.
ROOT = "file:///ROOT"
T = f"{ROOT}/t.py"
# Messages that the server sends of its own accord, kept apart.
LOGS = {"window/logMessage", "window/showMessage", "$/logTrace", "telemetry/event"}


def request(id: int, method: str, params: Json = None) -> Json:
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": params}


def notification(method: str, params: Json = None) -> Json:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def initialize(encodings: Sequence[str] | None = None) -> Json:
    capabilities = {"general": {"positionEncodings": encodings}} if encodings else {}
    params = {"processId": None, "rootUri": ROOT, "capabilities": capabilities}
    return request(1, "initialize", params)


START = [initialize(), notification("initialized", {})]
SHUTDOWN = request(2, "shutdown")
EXIT = notification("exit")


def did_open(text: str, uri: str = T) -> Json:
    document = {"uri": uri, "languageId": "python", "version": 1, "text": text}
    return notification("textDocument/didOpen", {"textDocument": document})


def did_change(*changes: Json) -> Json:
    params = {"textDocument": {"uri": T, "version": 2}, "contentChanges": changes}
    return notification("textDocument/didChange", params)


def formatting(uri: str = T) -> Json:
    options = {"tabSize": 4, "insertSpaces": True}
    params = {"textDocument": {"uri": uri}, "options": options}
    return request(10, "textDocument/formatting", params)


def session(*messages: Json, encodings: Sequence[str] | None = None) -> list[Json]:
    """``messages`` between the start and the end that the spec asks for."""
    return [initialize(encodings), START[1], *messages, SHUTDOWN, EXIT]


def position(text: str) -> Json:
    line, character = map(int, text.split(":"))
    return {"line": line, "character": character}


def span(start: str, end: str) -> Json:
    return {"start": position(start), "end": position(end)}


def change(start: str, end: str, text: str) -> Json:
    return {"range": span(start, end), "text": text}


def diagnostic(rule: str, start: str, end: str) -> Json:
    # The CLI adds " (has autofix)" to the message; the LSP does not.
    message = MESSAGES[rule].removesuffix(" (has autofix)")
    return {
        "range": span(start, end),
        "message": message,
        "severity": 2,
        "code": rule,
        "source": "fixit",
    }


def published(*found: tuple[str, str, str], uri: str = T, version: int = 1) -> Json:
    diagnostics = [diagnostic(*d) for d in found]
    return {"uri": uri, "diagnostics": diagnostics, "version": version}


def edit(start: str, end: str, text: str) -> list[Json]:
    return [{"range": span(start, end), "newText": text}]


@dataclass(frozen=True)
class Served:
    exit_code: object
    stderr: str
    # The header lines of each message, after Content-Length.
    headers: list[list[str]] = field(default_factory=list)
    # Responses by id, without "id" and "jsonrpc".
    responses: dict[int, Json] = field(default_factory=dict)
    # The params of each textDocument/publishDiagnostics, in order.
    published: list[Json] = field(default_factory=list)
    logs: list[Json] = field(default_factory=list)


class Stdout(io.BytesIO):
    """The server closes stdout on ``exit``; keep what it wrote."""

    def close(self) -> None:
        pass


def serve(files: Mapping[str, str], messages: Sequence[Json]) -> Served:
    """Write ``files`` to a new directory and send ``messages`` to ``fixit lsp``."""
    with TemporaryDirectory() as td:
        root = Path(td).resolve()
        for name, text in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
        stdin = b""
        for m in messages:
            body = json.dumps(m).replace(ROOT, root.as_uri()).encode()
            stdin += b"Content-Length: %d\r\n\r\n%s" % (len(body), body)
        stdout, stderr = Stdout(), io.StringIO()
        exit_code: object = None
        with (
            chdir(root),
            fresh_logging(),
            warnings.catch_warnings(),
            patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(stdin))),
            redirect_stdout(io.TextIOWrapper(stdout)),
            redirect_stderr(stderr),
        ):
            warnings.simplefilter("ignore", DeprecationWarning)
            try:
                main.main(["lsp", "--debounce-interval", "0"], prog_name="fixit")
            except SystemExit as e:
                exit_code = e.code
        data, received = stdout.getvalue(), []
        served = Served(exit_code, stderr.getvalue())
        while data:
            head, _, data = data.partition(b"\r\n\r\n")
            length, *headers = head.decode().split("\r\n")
            size = int(length.removeprefix("Content-Length: "))
            body, data = data[:size].decode(), data[size:]
            body = body.replace(root.as_uri(), ROOT).replace(str(root), "/ROOT")
            served.headers.append(headers)
            received.append(json.loads(body))
    for message in received:
        if "method" not in message:
            del message["jsonrpc"]
            served.responses[message.pop("id")] = message
        elif message["method"] == "textDocument/publishDiagnostics":
            served.published.append(message["params"])
        elif message["method"] in LOGS:
            served.logs.append(message)
        else:
            raise AssertionError(f"unexpected message: {message}")
    return served


def in_order(published: Sequence[Json]) -> list[Json]:
    """
    The diagnostics of one rule come in the order of the source. Between rules
    the order changes between runs, so those are sorted.
    """
    result = []
    for p in published:
        found = p["diagnostics"]
        if len({d["code"] for d in found}) > 1:
            found = sorted(found, key=lambda d: json.dumps(d, sort_keys=True))
        result.append({**p, "diagnostics": found})
    return result


# (label, rule, source, result of formatting)
# The edit replaces the whole text: to the position after its last character,
# with the lines of LSP 3.17 "Text Documents" (#21). The libcst engine ended it
# past the end of the last line, by the length of the line break, and counted
# the lines of str.splitlines().
FORMATTING = (
    (
        "fix",
        UI,
        f"x = 1\n{CALL}\ny = 2\n",
        edit("0:0", "3:0", f"x = 1\n{FIXED}\ny = 2\n"),
    ),
    ("fix, 1 line", UI, f"{CALL}\n", edit("0:0", "1:0", f"{FIXED}\n")),
    (
        "fix, CRLF",
        UI,
        f"x = 1\r\n{CALL}\r\n",
        edit("0:0", "2:0", f"x = 1\r\n{FIXED}\r\n"),
    ),
    # Nothing changes: no edit (#21).
    ("no autofix", SI, UNFIXABLE, None),
    ("no violation", UI, "x = 1\n", None),
    ("ignored", UI, f"{CALL}  # lint-ignore\n", None),
    # U+2028 is not a line break in LSP.
    (
        "U+2028",
        UI,
        f'{CALL}\nx = "\u2028"\n',
        edit("0:0", "2:0", f'{FIXED}\nx = "\u2028"\n'),
    ),
    # 😀 is 2 UTF-16 units, but the edit ends after the last line break.
    ("emoji", UI, f'{CALL}\nx = "😀"\n', edit("0:0", "2:0", f'{FIXED}\nx = "😀"\n')),
    # The comment is kept: the fix edits the name and the arguments.
    (
        "comment in the range",
        UI,
        "self.assertTrue(\n    a in b  # c\n)\n",
        edit("0:0", "3:0", "self.assertIn(\n    a,\n    b,  # c\n)\n"),
    ),
)
# The texts that ruff format changes, besides the fix.
# (label, rule, source, result of formatting)
FORMATTING_UNFORMATTED = (
    # ruff format adds "\n" at the end.
    (
        "no line break at end",
        UI,
        f"x = 1\n{CALL}",
        edit("0:0", "1:23", f"x = 1\n{FIXED}\n"),
    ),
    # The end of the last line counts 😀 as 2 UTF-16 units.
    (
        "emoji at the end",
        UI,
        f'{CALL}\nx = "😀"',
        edit("0:0", "1:8", f'{FIXED}\nx = "😀"\n'),
    ),
    # ruff format keeps "\r" at the end, which libcst dropped.
    ("CR", UI, f"x = 1\r{CALL}\r", edit("0:0", "2:0", f"x = 1\r{FIXED}\r")),
    # The BOM counts as a character, and stays in newText.
    ("BOM", UI, f"\ufeff{CALL}\n", edit("0:0", "1:0", f"\ufeff{FIXED}\n")),
)


class LspCharacterizationTest(CharacterizationTestCase):
    def assert_published(self, served: Served, *expected: Json) -> None:
        self.assertEqual(in_order(served.published), in_order(expected))
        # The server shows no error to the user.
        self.assertEqual(served.logs, [])

    def test_initialize_result_by_position_encodings_of_client(self) -> None:
        unknown = "WARNING:pygls.capabilities:Unknown `PositionEncoding`s: ('x',)\n"
        cases = (
            ("none", None, "utf-16", ""),
            ("utf-8", ["utf-8"], "utf-8", ""),
            ("first known of the client", ["x", "utf-32", "utf-16"], "utf-32", ""),
            ("unknown only", ["x"], "utf-16", unknown),
        )
        for label, encodings, encoding, stderr in cases:
            with self.subTest(label):
                served = serve({}, session(encodings=encodings))
                # NOTE: it offers executeCommand with no commands, and workspace
                # folders, which it does not use.
                folders = {"supported": True, "changeNotifications": True}
                capabilities = {
                    "positionEncoding": encoding,
                    # 2: Incremental.
                    "textDocumentSync": {"openClose": True, "change": 2, "save": False},
                    "documentFormattingProvider": True,
                    "executeCommandProvider": {"commands": []},
                    "workspace": {"workspaceFolders": folders, "fileOperations": {}},
                }
                info = {"name": "fixit-lsp", "version": __version__}
                result = {"capabilities": capabilities, "serverInfo": info}
                self.assertEqual(served.responses[1], {"result": result})
                self.assertEqual(served.stderr, stderr)

    def test_every_message_has_the_content_type_header(self) -> None:
        files = {"pyproject.toml": config(UI)}
        served = serve(files, session(did_open(f"{CALL}\n"), formatting()))
        header = "Content-Type: application/vscode-jsonrpc; charset=utf-8"
        self.assertEqual(served.headers, [[header]] * 4)

    def test_exit_code(self) -> None:
        cases = (
            ("after shutdown", [*START, SHUTDOWN, EXIT], 0),
            # NOTE: LSP 3.17 "exit": without shutdown, the exit code should be 1.
            ("without shutdown", [*START, EXIT], 0),
        )
        for label, messages, exit_code in cases:
            with self.subTest(label):
                self.assertEqual(serve({}, messages).exit_code, exit_code)

    def test_diagnostics_after_did_open(self) -> None:
        twice = f"{CALL}\nx = 1\nself.assertFalse(c in d)\n"
        ignored = f"{CALL}  # lint-ignore\nself.assertTrue(c in d)\n"
        cases = (
            ("no violation", (UI,), "x = 1\n", ()),
            ("empty", (UI,), "", ()),
            # 1 violation: test_diagnostic_range_and_message_of_each_rule.
            (
                "same rule twice",
                (UI,),
                twice,
                ((UI, "0:0", "0:23"), (UI, "2:0", "2:24")),
            ),
            ("2 rules", (NA, SI), FIXABLE + UNFIXABLE, (NA_0, SI_1)),
            ("1 of 2 ignored", (UI,), ignored, ((UI, "1:0", "1:23"),)),
            # NOTE: the syntax error is not reported, and hides the violation.
            ("syntax error", (UI,), f"{CALL}\nprint)\n", ()),
        )
        for label, rules, text, found in cases:
            with self.subTest(label):
                files = {"pyproject.toml": config(*rules)}
                served = serve(files, session(did_open(text)))
                self.assert_published(served, published(*found))

    def test_diagnostic_range_and_message_of_each_rule(self) -> None:
        nt = "from typing import NamedTuple\n\n\n"
        doc = '    """@sorted-attributes"""\n\n'
        cb = "from typing import Callable\n\n"
        cases = (
            (UI, f"{CALL}\n", "0:0", "0:23"),
            (UI, "self.assertTrue(\n    a in b\n)\n", "0:0", "2:1"),
            (NA, FIXABLE, "0:0", "0:21"),
            (NN, "self.assertTrue(a is not None)\n", "0:0", "0:30"),
            (SI, "if True:\n    pass\nelse:\n    x = 1\n", "0:0", "3:9"),
            (NT, f"{nt}class Foo(NamedTuple):\n    a: int\n", "3:0", "4:10"),
            (SA, f"class C:\n{doc}    b = 1\n    a = 2\n", "0:0", "4:9"),
            (VC, f"{cb}x: Callable[[...], int]\n", "2:3", "2:23"),
        )
        for rule, text, start, end in cases:
            with self.subTest(rule, text=text):
                files = {"pyproject.toml": config(rule)}
                served = serve(files, session(did_open(text)))
                self.assert_published(served, published((rule, start, end)))

    def assert_positions(self, cases: Sequence[tuple[Any, ...]]) -> None:
        for label, encodings, text, start, end in cases:
            with self.subTest(label, text=text):
                messages = session(did_open(text), encodings=encodings)
                served = serve({"pyproject.toml": config(UI)}, messages)
                self.assert_published(served, published((UI, start, end)))

    def test_positions_kept_by_new_engine(self) -> None:
        crlf = "x = 1\r\nself.assertTrue(\r\n    a in b\r\n)\r\n"
        cases = (
            ("full-width before", None, f'x = "あ"; {CALL}\n', "0:9", "0:32"),
            ("tab before", None, f"x = 1;\t{CALL}\n", "0:7", "0:30"),
            ("emoji on the line above", None, f'x = "😀"\n{CALL}\n', "1:0", "1:23"),
            ("emoji after", None, f'{CALL}; x = "😀"\n', "0:0", "0:23"),
            ("utf-32, emoji before", ["utf-32"], f'x = "😀"; {CALL}\n', "0:9", "0:32"),
            ("CRLF", None, f"x = 1\r\n\r\n{CALL}\r\n", "2:0", "2:23"),
            ("CRLF, 3 lines", None, crlf, "1:0", "3:1"),
            ("CR", None, f"x = 1\r\r{CALL}\r", "2:0", "2:23"),
            # Not a line break in LSP, unlike in str.splitlines.
            ("U+2028", None, f'x = "\u2028"; {CALL}\n', "0:9", "0:32"),
            # The BOM counts as a character in the text of the client (#21); the
            # libcst engine did not count it.
            ("BOM", None, f"\ufeff{CALL}\n", "0:1", "0:24"),
        )
        self.assert_positions(cases)

    def test_positions_in_the_units_of_the_client(self) -> None:
        # In the units agreed with the client, UTF-16 by default (#21). The
        # libcst engine counted code points.
        cases = (
            # 😀 is 2 UTF-16 units.
            ("emoji before", None, f'x = "😀"; {CALL}\n', "0:10", "0:33"),
            ("emoji inside", None, 'self.assertTrue(a in "😀")\n', "0:0", "0:26"),
            (
                "emoji, 2 lines",
                None,
                'self.assertTrue(\n    a in "😀")\n',
                "0:0",
                "1:14",
            ),
            # あ is 3 UTF-8 bytes.
            ("utf-8, あ before", ["utf-8"], f'x = "あ"; {CALL}\n', "0:11", "0:34"),
            # The BOM is on the first line only.
            ("BOM, line 2", None, f"\ufeffx = 1\n{CALL}\n", "1:0", "1:23"),
        )
        self.assert_positions(cases)

    def test_diagnostics_after_did_change(self) -> None:
        dirty, line_1 = f"x = 1\n{CALL}\n", ((UI, "1:0", "1:23"),)
        insert = change("1:0", "1:0", f"{CALL}\n")
        cases = (
            ("whole, adds", "x = 1\n", [{"text": dirty}], (), line_1),
            ("whole, removes", dirty, [{"text": "x = 1\n"}], line_1, ()),
            ("insert, adds", "x = 1\n", [insert], (), line_1),
            ("delete, removes", dirty, [change("1:0", "2:0", "")], line_1, ()),
            (
                "replace, adds",
                "self.assertTrue(a == b)\n",
                [change("0:18", "0:20", "in")],
                (),
                ((UI, "0:0", "0:23"),),
            ),
            # Applied in order: the 2nd range is in the text after the 1st.
            (
                "2 changes",
                "x = 1\n",
                [insert, change("0:0", "1:0", "")],
                (),
                ((UI, "0:0", "0:23"),),
            ),
            # The range is in UTF-16: 0:8 is the end of the line.
            (
                "after emoji",
                'x = "😀"\n',
                [change("0:8", "0:8", f"\n{CALL}")],
                (),
                line_1,
            ),
        )
        for label, text, changes, before, after in cases:
            with self.subTest(label):
                messages = session(did_open(text), did_change(*changes))
                served = serve({"pyproject.toml": config(UI)}, messages)
                after_ = published(*after, version=2)
                self.assert_published(served, published(*before), after_)

    def assert_formatting(self, cases: Sequence[tuple[Any, ...]]) -> None:
        for label, rule, text, result in cases:
            with self.subTest(label, text=text):
                messages = session(did_open(text), formatting())
                served = serve({"pyproject.toml": config(rule)}, messages)
                self.assertEqual(served.responses[10], {"result": result})
                self.assertEqual(served.logs, [])

    def test_formatting_result(self) -> None:
        self.assert_formatting(FORMATTING)

    def test_formatting_with_syntax_error(self) -> None:
        # Not in FORMATTING: `ruff format` fails on it.
        self.assert_formatting((("syntax error", UI, f"{CALL}\nprint)\n", None),))

    def test_formatting_of_unformatted_text(self) -> None:
        self.assert_formatting(FORMATTING_UNFORMATTED)

    def test_formatting_cases_under_ruff_format(self) -> None:
        # Not a test of fixit: checks that the cases above fit the new engine.
        stable = []
        for _, _, text, result in FORMATTING:
            stable += [text, *(e["newText"] for e in result or ())]
        # The engine formats the text without its BOM, and puts it back.
        unformatted = FORMATTING_UNFORMATTED
        stable += [e["newText"].removeprefix(BOM) for *_, r in unformatted for e in r]
        self.assertEqual(ruff_format(*stable), stable)

    def test_formatting_of_document_not_opened(self) -> None:
        with self.subTest("on disk"):
            files = {"pyproject.toml": config(NA), "t.py": FIXABLE}
            served = serve(files, session(formatting()))
            # The text is read from the file.
            result = edit("0:0", "1:0", "self.assertEqual(a, 3)\n")
            self.assertEqual(served.responses[10], {"result": result})
        with self.subTest("not on disk"):
            served = serve({"pyproject.toml": config(NA)}, session(formatting()))
            error = served.responses[10]["error"]
            # NOTE: the traceback of the server is sent to the client.
            self.assertEqual(list(error.pop("data")), ["traceback"])
            message = "FileNotFoundError: [Errno 2] No such file or directory:"
            message += " '/ROOT/t.py'"
            self.assertEqual(error, {"code": -32603, "message": message})

    def test_config_is_looked_up_from_document_path(self) -> None:
        both = config(NA, SI)
        two = {"a/pyproject.toml": config(NA), "b/pyproject.toml": config(SI)}
        cases = (
            ("2 dirs, 2 configs", two, {"a/t.py": (NA_0,), "b/t.py": (SI_1,)}),
            ("dir not on disk", {"pyproject.toml": both}, {"no/t.py": (NA_0, SI_1)}),
            # The file on disk is not read.
            (
                "file on disk",
                {"pyproject.toml": both, "t.py": UNFIXABLE + FIXABLE},
                {"t.py": (NA_0, SI_1)},
            ),
        )
        for label, files, found in cases:
            with self.subTest(label):
                uris = {f"{ROOT}/{path}": f for path, f in found.items()}
                opened = [did_open(FIXABLE + UNFIXABLE, uri) for uri in uris]
                served = serve(files, session(*opened))
                expected = [published(*f, uri=uri) for uri, f in uris.items()]
                self.assert_published(served, *expected)

    def test_uri_of_document(self) -> None:
        files = {"pyproject.toml": config(NA), "a b/pyproject.toml": config(SI)}
        text = FIXABLE + UNFIXABLE
        fixed = edit("0:0", "3:0", "self.assertEqual(a, 3)\n" + UNFIXABLE)
        cases = (
            # Not linted; nothing is published.
            ("untitled", "untitled:Untitled-1", None, None),
            # The path is decoded; the URI is published as sent.
            ("percent-encoded", f"{ROOT}/a%20b/t.py", SI_1, None),
            # NOTE: neither the suffix nor languageId is looked at.
            ("not .py", f"{ROOT}/t.txt", NA_0, fixed),
        )
        for label, uri, found, result in cases:
            with self.subTest(label):
                served = serve(files, session(did_open(text, uri), formatting(uri)))
                expected = [] if found is None else [published(found, uri=uri)]
                self.assert_published(served, *expected)
                self.assertEqual(served.responses[10], {"result": result})
