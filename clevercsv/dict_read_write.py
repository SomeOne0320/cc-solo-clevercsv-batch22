# -*- coding: utf-8 -*-

"""
DictReader and DictWriter.

This code is entirely copied from the Python csv module. The only exception is
that it uses the `reader` and `writer` classes from our package.

Author: Gertjan van den Burg

"""

from __future__ import annotations

import warnings

from collections import OrderedDict
from collections.abc import Collection
from collections.abc import Mapping as _MappingABC

from typing import TYPE_CHECKING
from typing import Any
from typing import Generic
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Literal
from typing import Mapping
from typing import Optional
from typing import Sequence
from typing import TypeVar
from typing import Union
from typing import cast

from clevercsv.read import reader
from clevercsv.write import writer

if TYPE_CHECKING:
    from clevercsv._types import SupportsWrite
    from clevercsv._types import _DialectLike
    from clevercsv._types import _DictReadMapping
    from clevercsv._types import _DictReadColumnSelector

_T = TypeVar("_T")


class DictReader(
    Generic[_T], Iterator["_DictReadMapping[Union[_T, Any], Union[str, Any]]"]
):
    """Read a CSV file as dictionaries

    Behaves like :class:`csv.DictReader`, using CleverCSV's :class:`reader`
    underneath. The optional ``columns`` argument takes an ordered mapping
    whose keys are the keys delivered in the output dictionaries and whose
    values identify header columns: either a header name (allowed only when
    the name occurs exactly once in the header) or a ``(name, occurrence)``
    tuple, where the occurrence is counted from one to disambiguate duplicate
    header names. The mapping is resolved against the header as soon as the
    header is read; an unknown name or an ambiguous bare name raises a
    :class:`ValueError` before any data row is delivered. Selected columns are
    output in mapping order; short rows keep using ``restval`` and values
    beyond the header keep using ``restkey``.
    """

    def __init__(
        self,
        f: Iterable[str],
        fieldnames: Optional[Sequence[_T]] = None,
        restkey: Optional[str] = None,
        restval: Optional[str] = None,
        dialect: "_DialectLike" = "excel",
        columns: Optional["_DictReadColumnSelector[_T]"] = None,
        *args: Any,
        **kwds: Any,
    ) -> None:
        if columns is not None and not isinstance(columns, _MappingABC):
            raise TypeError(
                "columns must be a mapping from output keys to header "
                "names (or (header name, occurrence) tuples)"
            )
        self._fieldnames = fieldnames
        self._raw_fieldnames: Optional[List[Any]] = (
            list(fieldnames) if fieldnames is not None else None
        )
        self._columns = columns
        self._column_indexes: Optional[List[int]] = None
        self.restkey = restkey
        self.restval = restval
        self.reader: reader = reader(f, dialect, *args, **kwds)
        self.dialect = dialect
        self.line_num = 0

    def __iter__(self) -> "DictReader[_T]":
        return self

    @property
    def fieldnames(self) -> Optional[Sequence[_T]]:
        if self._raw_fieldnames is None:
            try:
                header = next(self.reader)
            except StopIteration:
                return None
            self._raw_fieldnames = list(header)
            self.line_num = self.reader.line_num

        raw_fieldnames: List[Any] = self._raw_fieldnames

        # Note: this was added because I don't think it's expected that Python
        # simply drops information if there are duplicate headers. There is
        # discussion on this issue in the Python bug tracker here:
        # https://bugs.python.org/issue17537 (see linked thread therein). A
        # warning is easy enough to suppress and should ensure that the user
        # is at least aware of this behavior.
        if self._columns is None and not len(raw_fieldnames) == len(
            set(raw_fieldnames)
        ):
            warnings.warn(
                "fieldnames are not unique, some columns will be dropped."
            )

        if self._columns is not None and self._column_indexes is None:
            self._column_indexes = self._resolve_columns()
            self._fieldnames = list(self._columns.keys())

        if self._fieldnames is None:
            self._fieldnames = [cast(_T, f) for f in raw_fieldnames]

        fieldnames: Sequence[_T] = self._fieldnames
        return fieldnames

    @fieldnames.setter
    def fieldnames(self, value: Sequence[_T]) -> None:
        # Explicitly setting fieldnames overrides any pending columns mapping,
        # matching the stdlib escape hatch.
        self._fieldnames = value
        self._raw_fieldnames = list(value)
        self._columns = None
        self._column_indexes = None

    def _resolve_columns(self) -> List[int]:
        """Resolve the columns mapping against the header, by position

        Each mapping entry refers to a header column either by its name (only
        allowed when the name occurs exactly once in the header) or by a
        ``(name, occurrence)`` tuple where occurrence counts from one. Raises a
        :class:`ValueError` when a column can't be located or when a bare name
        is ambiguous, so that no data rows are delivered with an invalid
        mapping.
        """
        assert self._columns is not None
        assert self._raw_fieldnames is not None
        header = self._raw_fieldnames
        indexes: List[int] = []
        for output_key, selector in self._columns.items():
            occurrence: Optional[int]
            if isinstance(selector, tuple) and len(selector) == 2:
                name, occurrence = selector
            else:
                name = selector
                occurrence = None
            matches = [i for i, field in enumerate(header) if field == name]
            if occurrence is None:
                if not matches:
                    raise ValueError(
                        f"column {name!r} (for key {output_key!r}) not found "
                        "in the header"
                    )
                if len(matches) > 1:
                    raise ValueError(
                        f"column {name!r} (for key {output_key!r}) occurs "
                        f"{len(matches)} times in the header; specify the "
                        "occurrence as (name, n), counted from 1"
                    )
                indexes.append(matches[0])
            else:
                if not isinstance(occurrence, int) or occurrence < 1:
                    raise ValueError(
                        "the occurrence in a (name, occurrence) selector must "
                        "be a positive integer, counting from 1"
                    )
                if occurrence > len(matches):
                    raise ValueError(
                        f"column {name!r} (for key {output_key!r}) "
                        f"occurs only {len(matches)} time(s), occurrence "
                        f"{occurrence} doesn't exist"
                    )
                indexes.append(matches[occurrence - 1])
        return indexes

    def __next__(self) -> "_DictReadMapping[Union[_T, Any], Union[str, Any]]":
        if self.line_num == 0:
            self.fieldnames
        row = next(self.reader)
        self.line_num = self.reader.line_num

        while row == []:
            row = next(self.reader)

        d: _DictReadMapping = OrderedDict()
        assert self._raw_fieldnames is not None
        raw_fieldnames: List[Any] = self._raw_fieldnames
        if self._columns is None:
            lf = len(raw_fieldnames)
            for key, value in zip(raw_fieldnames, row):
                d[cast(Any, key)] = value
        else:
            assert self.fieldnames is not None
            assert self._column_indexes is not None
            lr = len(row)
            lf = len(raw_fieldnames)
            for key, index in zip(self.fieldnames, self._column_indexes):
                d[cast(Any, key)] = row[index] if index < lr else self.restval

        if lf < len(row):
            d[self.restkey] = row[lf:]
        elif self._columns is None and lf > len(row):
            for key in raw_fieldnames[len(row):]:
                d[cast(Any, key)] = self.restval
        return d


class DictWriter(Generic[_T]):
    def __init__(
        self,
        f: SupportsWrite[str],
        fieldnames: Collection[_T],
        restval: Optional[Any] = "",
        extrasaction: Literal["raise", "ignore"] = "raise",
        dialect: "_DialectLike" = "excel",
        *args: Any,
        **kwds: Any,
    ):
        self.fieldnames = fieldnames
        self.restval = restval
        if extrasaction.lower() not in ("raise", "ignore"):
            raise ValueError(
                "extrasaction (%s) must be 'raise' or 'ignore'" % extrasaction
            )
        self.extrasaction = extrasaction
        self.writer = writer(f, dialect, *args, **kwds)

    def writeheader(self) -> Any:
        header = dict(zip(self.fieldnames, self.fieldnames))
        return self.writerow(header)

    def _dict_to_list(self, rowdict: Mapping[_T, Any]) -> Iterator[Any]:
        if self.extrasaction == "raise":
            wrong_fields = rowdict.keys() - self.fieldnames
            if wrong_fields:
                raise ValueError(
                    "dict contains fields not in fieldnames: "
                    + ", ".join([repr(x) for x in wrong_fields])
                )
        return (rowdict.get(key, self.restval) for key in self.fieldnames)

    def writerow(self, rowdict: Mapping[_T, Any]) -> Any:
        return self.writer.writerow(self._dict_to_list(rowdict))

    def writerows(self, rowdicts: Iterable[Mapping[_T, Any]]) -> None:
        return self.writer.writerows(map(self._dict_to_list, rowdicts))
