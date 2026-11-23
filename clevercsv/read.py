# -*- coding: utf-8 -*-

"""
Drop-in replacement for the Python csv reader class. This is a wrapper for the
Parser class, defined in :mod:`cparser`.

Author: Gertjan van den Burg

"""

import csv

from typing import Any
from typing import Iterable
from typing import Iterator
from typing import List

from . import field_size_limit
from ._types import _DialectLike
from .cparser import Error as ParserError
from .cparser import Parser
from .dialect import SimpleDialect
from .exceptions import Error


class _LineCountingIterator(Iterator[str]):
    """Iterator wrapper that counts the physical lines taken from it

    The counter is incremented every time a line is pulled from the wrapped
    iterator, including lines that are part of a quoted field spanning
    multiple lines or blank lines in the middle of the input. This mirrors the
    bookkeeping of the line number in the standard library ``csv`` module and
    backs the :attr:`reader.line_num` attribute.

    """

    def __init__(self, csvfile: Iterable[str]) -> None:
        self._iterator: Iterator[str] = iter(csvfile)
        self.line_num: int = 0

    def __iter__(self) -> "_LineCountingIterator":
        return self

    def __next__(self) -> str:
        line = next(self._iterator)
        self.line_num += 1
        return line


class reader:
    def __init__(
        self,
        csvfile: Iterable[str],
        dialect: _DialectLike = "excel",
        **fmtparams: Any,
    ):
        self.csvfile = csvfile
        self.original_dialect = dialect
        self._dialect = self._make_simple_dialect(dialect, **fmtparams)
        # The parser is created once and owns the (forward-only) input
        # iterator. Repeated calls to ``__iter__`` therefore resume at the
        # current position instead of restarting the input; only a freshly
        # constructed reader starts reading from the beginning again.
        self._line_iter = _LineCountingIterator(csvfile)
        self.parser_gen: Parser = Parser(
            self._line_iter,
            delimiter=self._dialect.delimiter,
            quotechar=self._dialect.quotechar,
            escapechar=self._dialect.escapechar,
            field_limit=field_size_limit(),
            strict=self._dialect.strict,
        )

    @property
    def dialect(self) -> csv.Dialect:
        return self._dialect.to_csv_dialect()

    @property
    def line_num(self) -> int:
        # Number of physical lines taken from the input iterator so far.
        return self._line_iter.line_num

    @line_num.setter
    def line_num(self, value: int) -> None:
        # The standard library allows ``line_num`` to be assigned, so keep
        # the attribute writable for compatibility.
        self._line_iter.line_num = value

    def _make_simple_dialect(
        self, dialect: _DialectLike, **fmtparams: Any
    ) -> SimpleDialect:
        if isinstance(dialect, str):
            sd = SimpleDialect.from_csv_dialect(csv.get_dialect(dialect))
        elif isinstance(dialect, csv.Dialect):
            sd = SimpleDialect.from_csv_dialect(dialect)
        elif isinstance(dialect, SimpleDialect):
            sd = dialect
        else:
            raise ValueError("Unknown dialect type: %r" % dialect)
        for key, value in fmtparams.items():
            if key in ["delimiter", "quotechar", "escapechar", "strict"]:
                setattr(sd, key, value)
        sd.validate()
        return sd

    def __iter__(self) -> "reader":
        # A reader is a one-shot, forward-only iterator: ``iter(reader)``
        # always returns the same reader at its current position.
        return self

    def __next__(self) -> List[str]:
        try:
            row = next(self.parser_gen)
        except ParserError as e:
            raise Error(str(e))
        # ``line_num`` reflects the physical lines consumed during this read,
        # including lines belonging to multiline quoted fields, so it is
        # up to date even when a parse error is raised.
        return row
