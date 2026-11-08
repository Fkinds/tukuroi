# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Positions in source text, counted in characters: the indexes of a Python ``str``.

The engine keeps a range of text as a :class:`Span` of offsets into the whole
text, and turns an offset into a line and a column (a :class:`Range` for a
span) only to show it.
:class:`LineIndex` converts between them, and from the columns of ``ast``,
which count UTF-8 bytes.

Lines end with ``"\\n"``, ``"\\r\\n"`` or ``"\\r"``, as in the Python language
reference (2.1.2, "Physical lines"). The other characters that
``str.splitlines()`` takes as line breaks, such as ``"\\f"`` and U+2028, count as
one character of a line.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass

_LINE_END = re.compile(r"\r\n|\r|\n")


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """A line, counted from 1, and a column in characters, counted from 0."""

    line: int
    column: int

    def __post_init__(self) -> None:
        if self.line < 1 or self.column < 0:
            raise ValueError(
                f"invalid position: line {self.line}, column {self.column}"
            )


@dataclass(frozen=True, slots=True, order=True)
class Span:
    """
    The offsets ``[start, end)`` into a text. An empty span (``start == end``) is
    the place to insert at.
    """

    start: int
    end: int

    def __post_init__(self) -> None:
        if not 0 <= self.start <= self.end:
            raise ValueError(f"invalid span: [{self.start}, {self.end})")


@dataclass(frozen=True, slots=True, order=True)
class Range:
    """From ``start`` to ``end``: the positions of a span, to show it."""

    start: Position
    end: Position

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"invalid range: {self.start} to {self.end}")


class LineIndex:
    """
    The lines of a text, to convert between offsets and positions.

    A column can be from 0 to the length of the line without its line end; a
    position inside a ``"\\r\\n"`` is not valid. The end of the text is a valid
    offset: after a line end, it is column 0 of the next line. So a text has one
    line more than it has line ends, and an empty text has one line.
    """

    __slots__ = ("_ends", "_starts", "_text")

    def __init__(self, text: str) -> None:
        starts, ends = [0], []
        for match in _LINE_END.finditer(text):
            ends.append(match.start())
            starts.append(match.end())
        ends.append(len(text))
        self._text = text
        # The offset of the start of each line, and of the end of its content.
        self._starts = tuple(starts)
        self._ends = tuple(ends)

    def offset(self, position: Position) -> int:
        """The offset of ``position``, whose column counts characters."""
        start, end = self._line(position.line)
        if position.column > end - start:
            raise ValueError(
                f"column {position.column} past the end of line {position.line}"
            )
        return start + position.column

    def offset_from_utf8(self, line: int, byte_column: int) -> int:
        """The offset of ``line`` and ``byte_column``, which counts UTF-8 bytes."""
        start, end = self._line(line)
        encoded = self._text[start:end].encode("utf-8")
        if not 0 <= byte_column <= len(encoded):
            raise ValueError(f"byte column {byte_column} out of line {line}")
        try:
            column = len(encoded[:byte_column].decode("utf-8"))
        except UnicodeDecodeError:
            message = f"byte column {byte_column} is inside a character"
            raise ValueError(f"{message} on line {line}") from None
        return start + column

    def position(self, offset: int) -> Position:
        """The line and the column in characters of ``offset``."""
        if not 0 <= offset <= len(self._text):
            raise ValueError(f"offset {offset} out of the text")
        index = bisect_right(self._starts, offset) - 1
        if offset > self._ends[index]:
            raise ValueError(f"offset {offset} is inside a line end")
        return Position(index + 1, offset - self._starts[index])

    def _line(self, line: int) -> tuple[int, int]:
        """The offsets of the start and the end of the content of ``line``."""
        if not 1 <= line <= len(self._starts):
            raise ValueError(f"no line {line}")
        return self._starts[line - 1], self._ends[line - 1]
