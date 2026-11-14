# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import re
import threading
from collections.abc import Callable, Generator
from functools import partial
from pathlib import Path
from typing import Any, TypeVar, cast

import pygls.uris as Uri
from lsprotocol.types import (
    SHUTDOWN,
    TEXT_DOCUMENT_DID_CHANGE,
    TEXT_DOCUMENT_DID_OPEN,
    TEXT_DOCUMENT_FORMATTING,
    Diagnostic,
    DiagnosticSeverity,
    DidChangeTextDocumentParams,
    DidOpenTextDocumentParams,
    DocumentFormattingParams,
    LogMessageParams,
    LSPErrorCodes,
    MessageType,
    Position,
    PublishDiagnosticsParams,
    Range,
    TextEdit,
)
from pygls.exceptions import JsonRpcException
from pygls.lsp.server import LanguageServer
from pygls.workspace.text_document import TextDocument

from .__version__ import __version__
from .api import _error, fixit_bytes
from .config import ConfigError, generate_config
from .ftypes import FileContent, LSPOptions, Options, Result
from .util import capture

# Line breaks of LSP 3.17 ("Text Documents"): not those of str.splitlines(),
# which also breaks at U+2028 and others.
_LINE_BREAK = re.compile(r"\r\n|\r|\n")
BOM = "\ufeff"


def lines_of(text: str) -> list[str]:
    """The lines of ``text`` as LSP counts them, without their line breaks."""
    return _LINE_BREAK.split(text)


class LSP:
    """
    Server for the Language Server Protocol.
    Provides diagnostics as you type, and exposes a formatter.
    https://microsoft.github.io/language-server-protocol/
    """

    def __init__(self, tukuroi_options: Options, lsp_options: LSPOptions) -> None:
        self.tukuroi_options = tukuroi_options
        self.lsp_options = lsp_options

        # separate debounce timer per URI so that linting one URI
        # doesn't cancel linting another
        self._validate_uri: dict[str, Callable[[int], None]] = {}
        # Whether the client asked to shut down before "exit" (LSP 3.17).
        self.shut_down = False

        self.lsp = LanguageServer("fixit-lsp", __version__)
        # `partial` since `pygls` can register functions but not methods
        self.lsp.feature(TEXT_DOCUMENT_DID_OPEN)(partial(self.on_did_open))
        self.lsp.feature(TEXT_DOCUMENT_DID_CHANGE)(partial(self.on_did_change))
        self.lsp.feature(TEXT_DOCUMENT_FORMATTING)(partial(self.format))
        self.lsp.feature(SHUTDOWN)(partial(self.on_shutdown))

    def path_of(self, doc: TextDocument) -> Path | None:
        """
        The path of ``doc``, to look up its config from: ``None`` for a document
        that is not a file, or not in Python, as its client says (#96).
        """
        if doc.language_id != "python":
            return None
        path = Uri.to_fs_path(doc.uri)
        return Path(path) if path else None

    def lint(
        self, doc: TextDocument, path: Path, *, autofix: bool = False
    ) -> Generator[Result, bool, FileContent | None]:
        """
        :func:`~tukuroi.api.fixit_bytes` on the text of ``doc``. The config is
        read each time, so that a change to it is seen without a restart (#96);
        one that tukuroi cannot use, or a rule that it names that cannot be loaded,
        is the error of the document, as with :func:`~tukuroi.api.fixit_file`.
        """
        try:
            config = generate_config(path, options=self.tukuroi_options, check=True)
        except ConfigError as error:
            yield Result(path, violation=None, error=_error(error))
            return None
        content = doc.source.encode()
        return (yield from fixit_bytes(path, content, autofix=autofix, config=config))

    def position(self, text: str, line: int, column: int) -> Position:
        """
        The position in ``text``, the document of the client, of ``line`` (from
        1) and ``column`` (characters from 0) of the engine, in the units agreed
        with the client (UTF-16 by default). The engine does not count a BOM;
        the client counts it as a character (#21).
        """
        if line == 1 and text.startswith(BOM):
            column += 1
        codec = self.lsp.workspace.position_codec
        return codec.position_to_client_units(
            lines_of(text), Position(line - 1, column)
        )

    def diagnostic(self, text: str, result: Result) -> Diagnostic | None:
        """
        ``result`` as a diagnostic: a violation, or an error (#96). A syntax
        error is shown where it is, and another error, such as an exception in a
        rule or a config that tukuroi cannot use, at the start of the document.
        """
        if violation := result.violation:
            start, end = violation.range.start, violation.range.end
            return Diagnostic(
                Range(
                    self.position(text, start.line, start.column),
                    self.position(text, end.line, end.column),
                ),
                violation.message,
                severity=DiagnosticSeverity.Warning,
                code=violation.rule_name,
                source="fixit",
            )
        if error := result.error:
            where = error.position
            at = self.position(text, where.line, where.column) if where else None
            at = at or Position(0, 0)
            # An exception, with its traceback in the log: its type too.
            message = error.message
            if error.traceback:
                message = f"{error.type}: {message}"
            return Diagnostic(
                Range(at, at),
                message,
                severity=DiagnosticSeverity.Error,
                source="fixit",
            )
        return None

    def _validate(self, uri: str, version: int) -> None:
        """
        Effect: publishes tukuroi diagnostics to the LSP client. The traceback of
        an exception goes to the log of the client (#96).
        """
        doc = self.lsp.workspace.text_documents.get(uri)
        path = doc and self.path_of(doc)
        if not doc or not path:
            return
        diagnostics = []
        for result in self.lint(doc, path):
            if diagnostic := self.diagnostic(doc.source, result):
                diagnostics.append(diagnostic)
            if result.error and result.error.traceback:
                message = f"{path}:\n{result.error.traceback}"
                self.lsp.window_log_message(
                    LogMessageParams(MessageType.Error, message)
                )
        self.lsp.text_document_publish_diagnostics(
            PublishDiagnosticsParams(uri, diagnostics, version)
        )

    def validate(self, uri: str, version: int) -> None:
        """
        Effect: may publish tukuroi diagnostics to the LSP client after a debounce delay.
        """
        if uri not in self._validate_uri:
            self._validate_uri[uri] = debounce(self.lsp_options.debounce_interval)(
                partial(self._validate, uri)
            )
        self._validate_uri[uri](version)

    def on_did_open(self, params: DidOpenTextDocumentParams) -> None:
        self.validate(params.text_document.uri, params.text_document.version)

    def on_did_change(self, params: DidChangeTextDocumentParams) -> None:
        self.validate(params.text_document.uri, params.text_document.version)

    def on_shutdown(self, *args: object) -> None:
        self.shut_down = True

    def format(self, params: DocumentFormattingParams) -> list[TextEdit] | None:
        """
        The fixes of the document, as one edit of its whole text. ``None`` for
        a document that is not in Python, or has an error (#96). A document
        that is not open is an error: its text is the client's (LSP 3.17).
        """
        uri = params.text_document.uri
        doc = self.lsp.workspace.text_documents.get(uri)
        if doc is None:
            raise JsonRpcException(
                f"document is not open: {uri}", LSPErrorCodes.RequestFailed
            )
        path = self.path_of(doc)
        if path is None:
            return None

        captured = capture(self.lint(doc, path, autofix=True))
        for _ in captured:
            pass
        formatted_content = captured.result
        if not formatted_content:
            return None

        # The whole document: to the position after its last character (#21).
        lines = lines_of(doc.source)
        codec = self.lsp.workspace.position_codec
        end = codec.position_to_client_units(
            lines, Position(len(lines) - 1, len(lines[-1]))
        )
        entire_range = Range(start=Position(line=0, character=0), end=end)
        return [TextEdit(new_text=formatted_content.decode(), range=entire_range)]

    def start(self) -> int:
        """
        Effect: occupies stdin and stdout. The server talks over stdio only: it
        had TCP and WebSocket too, which anyone on the machine could connect to
        (#15). Returns the exit code of LSP 3.17 "exit": 0 after "shutdown",
        and 1 without (#96).
        """
        self.lsp.start_io()
        return 0 if self.shut_down else 1


VoidFunction = TypeVar("VoidFunction", bound=Callable[..., None])


class Debouncer:
    def __init__(self, f: Callable[..., Any], interval: float) -> None:
        self.f = f
        self.interval = interval
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.interval, self.f, args, kwargs)
            self._timer.start()


def debounce(interval: float) -> Callable[[VoidFunction], VoidFunction]:
    """
    Wait `interval` seconds before calling `f`, and cancel if called again.
    The decorated function will return None immediately,
    ignoring the delayed return value of `f`.
    """

    def decorator(f: VoidFunction) -> VoidFunction:
        if interval <= 0:
            return f
        return cast(VoidFunction, Debouncer(f, interval))

    return decorator
