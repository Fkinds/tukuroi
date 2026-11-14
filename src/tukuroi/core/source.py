# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The source of a file, read and parsed once for the rules and the engine.

:class:`Source` keeps the text with its line ends as they are, so that a fix
changes no byte outside the range it replaces, and writes the text back in the
encoding and with the BOM that the file had.
"""

import ast
import codecs
import io
import re
import tokenize
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from .text import LineIndex, Position, Span

_LINE_END = re.compile(rb"\r\n|\r|\n")


class ParseError(Exception):
    """The source cannot be decoded, parsed or tokenized."""

    def __init__(self, position: Position, message: str) -> None:
        super().__init__(message)
        self.position = position
        self.message = message


@dataclass(frozen=True, slots=True)
class Comment:
    """A comment: its span, and its text from ``#`` to the end of the line."""

    span: Span
    text: str


@dataclass(frozen=True, slots=True)
class Token:
    """
    A token of :mod:`tokenize`: its type (such as ``tokenize.NAME``), its
    string, its span, and the positions of the start and the end of the span
    (#144). The end of a token past the end of its line, as tokenize gives
    the line end tokens, is the start of the next line: a span is always in
    the text.
    """

    type: int
    string: str
    span: Span
    start: Position
    end: Position


@dataclass(frozen=True, slots=True, eq=False)
class Source:
    """
    A file read and parsed, with what the rules and the engine need of it.

    ``encoding`` is the name that ``tokenize.detect_encoding`` gives (such as
    ``"utf-8"`` or ``"iso-8859-1"``), or ``None`` when the source was made from
    text. ``bom`` is whether the text started with a BOM, which ``text`` does not
    have.
    """

    path: Path | None
    text: str
    encoding: str | None
    bom: bool
    tree: ast.Module
    lines: LineIndex
    tokens: tuple[Token, ...]
    comments: tuple[Comment, ...]

    @classmethod
    def from_bytes(cls, data: bytes, path: Path | None = None) -> Self:
        """
        Decode ``data`` as Python does: with the encoding of a BOM or of a
        declaration on the first two lines (PEP 263), or UTF-8 (PEP 3120).
        """
        try:
            encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        except SyntaxError as e:
            raise ParseError(Position(1, 0), str(e)) from e
        # "utf-8-sig" would count the position of an error without the BOM.
        bom = encoding == "utf-8-sig"
        if bom:
            data, encoding = data[len(codecs.BOM_UTF8) :], "utf-8"
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError as e:
            line = 1 + len(_LINE_END.findall(data, 0, e.start))
            raise ParseError(Position(line, 0), str(e)) from e
        return cls._parse(text, path, encoding, bom)

    @classmethod
    def from_text(cls, text: str, path: Path | None = None) -> Self:
        """
        Parse ``text``, which is already decoded. A BOM at its start is taken
        off, as when decoding bytes.
        """
        bom = text.startswith(codecs.BOM_UTF8.decode())
        return cls._parse(text[1:] if bom else text, path, None, bom)

    @classmethod
    def _parse(
        cls, text: str, path: Path | None, encoding: str | None, bom: bool
    ) -> Self:
        filename = "<unknown>" if path is None else str(path)
        try:
            tree = ast.parse(text, filename=filename)
        except SyntaxError as e:
            line, column = e.lineno or 1, max((e.offset or 1) - 1, 0)
            raise ParseError(Position(line, column), e.msg) from e
        lines = LineIndex(text)
        readline = io.StringIO(text, newline="").readline
        # The text parses, so it tokenizes: since Python 3.12, tokenize has the
        # tokenizer of the parser (#116).
        tokens = tuple(
            _token(lines, len(text), t) for t in tokenize.generate_tokens(readline)
        )
        comments = tuple(
            Comment(t.span, t.string) for t in tokens if t.type == tokenize.COMMENT
        )
        return cls(path, text, encoding, bom, tree, lines, tokens, comments)

    def tokens_in(self, span: Span) -> tuple[Token, ...]:
        """The tokens whose spans are in ``span``, in their order (#144)."""
        starts = [t.span.start for t in self.tokens]
        first = bisect_left(starts, span.start)
        found: list[Token] = []
        for token in self.tokens[first:]:
            if token.span.start > span.end:
                break
            if token.span.end <= span.end:
                found.append(token)
        return tuple(found)

    def span(self, node: ast.AST) -> Span:
        """
        The span of ``node``, a node of ``tree``. A ``Module`` spans the whole
        text; another node without a position raises ``TypeError``.
        """
        if isinstance(node, ast.Module):
            return Span(0, len(self.text))
        names = ("lineno", "col_offset", "end_lineno", "end_col_offset")
        values = [getattr(node, name, None) for name in names]
        if None in values:
            raise TypeError(f"{type(node).__name__} has no position")
        line, column, end_line, end_column = values
        start = self.lines.offset_from_utf8(line, column)
        return Span(start, self.lines.offset_from_utf8(end_line, end_column))

    def encode(self, text: str) -> bytes:
        """
        ``text``, a new text of this source, in its encoding and with its BOM.
        Raises ``UnicodeEncodeError`` when the encoding cannot write ``text``.
        """
        if self.encoding is None:
            raise ValueError("no encoding: the source was made from text")
        data = text.encode(self.encoding)
        return codecs.BOM_UTF8 + data if self.bom else data


def _token(lines: LineIndex, length: int, token: tokenize.TokenInfo) -> Token:
    """``token`` with its span and positions in the text."""
    start = _token_offset(lines, length, *token.start)
    end = _token_offset(lines, length, *token.end)
    return Token(
        token.type,
        token.string,
        Span(start, end),
        lines.position(start),
        lines.position(end),
    )


def _token_offset(lines: LineIndex, length: int, line: int, column: int) -> int:
    """
    The offset of a position of tokenize. A position past the end of its line,
    the end of a line end token, is the start of the next line; past the last
    line (``ENDMARKER``, or ``DEDENT`` at the end), it is the end of the text.
    """
    try:
        return lines.offset(Position(line, column))
    except ValueError:
        pass
    try:
        return lines.offset(Position(line + 1, 0))
    except ValueError:
        return length
