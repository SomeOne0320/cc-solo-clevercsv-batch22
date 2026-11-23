# -*- coding: utf-8 -*-

"""
Break ties in the data consistency measure.

Author: Gertjan van den Burg

"""

from dataclasses import dataclass
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from .cparser_util import parse_string
from .dialect import SimpleDialect
from .utils import pairwise


def tie_breaker(
    data: str, dialects: List[SimpleDialect]
) -> Optional[SimpleDialect]:
    """
    Break ties between dialects.

    This function is used to break ties where possible between two, three, or
    four dialects that receive the same value for the data consistency measure.

    Parameters
    ----------
    data: str
        The data as a single string
    dialects: list
        Dialects that are tied

    Returns
    -------
    dialect: SimpleDialect
        One of the dialects from the list provided or None.


    """
    if len(dialects) == 2:
        return break_ties_two(data, dialects[0], dialects[1])
    elif len(dialects) == 3:
        return break_ties_three(data, dialects[0], dialects[1], dialects[2])
    elif len(dialects) == 4:
        return break_ties_four(data, dialects)
    return None


@dataclass
class _PairStats:
    """Compact summary of how two dialects parse the same data.

    The information stored here is bounded: it never accumulates rows or
    cells, so the size of a summary does not depend on the number of rows in
    the file. At most a single cell value (the first cell on which the two
    parsers disagree) is retained, because that is all the tie breaking
    rules need.

    Attributes
    ----------
    equal : bool
        Whether the complete parsing results, including every cell, are
        identical.

    same_shape : bool
        Whether the parsing results have the same number of rows and whether
        corresponding rows have the same number of fields.

    same_row_count : bool
        Whether the two parsers produced the same number of rows. Tracked
        separately from :attr:`same_shape`, because one of the original tie
        breaking rules only inspects the row counts.

    first_diff : Optional[tuple]
        The ``(cell_of_first_dialect, cell_of_second_dialect)`` pair of the
        first differing cell, in the order in which the rows are read.
        ``None`` if the two parsers never disagree.

    all_diffs_have_seq : bool
        Whether every cell of the dialect without escape character that
        differs contains the sequence relevant for the escapechar+quotechar
        tie breaking rule. The cell is taken from whichever side of the pair
        does not use the escape character, matching the original rule.
        Remains ``True`` when the cells never differ.

    """

    equal: bool = True
    same_shape: bool = True
    same_row_count: bool = True
    first_diff: Optional[Tuple[str, str]] = None
    all_diffs_have_seq: bool = True


def _count_escaped_quotes(cell: str, escapechar: str, quotechar: str) -> int:
    """Count escapechar/quotechar adjacencies in a cell."""
    count = 0
    for a, b in pairwise(cell):
        if a == escapechar and b == quotechar:
            count += 1
    return count


def _compare_streaming(
    data: str,
    dialects: List[SimpleDialect],
    seq_pairs: Optional[Dict[Tuple[SimpleDialect, SimpleDialect], str]] = None,
) -> Dict[Tuple[SimpleDialect, SimpleDialect], _PairStats]:
    """Parse the data once per dialect and summarize pairwise differences.

    The dialects are parsed in lockstep, row by row. Each dialect is parsed
    at most a single time and no complete parsing result is retained. The
    per-pair summaries hold only a fixed amount of information, so the extra
    memory used by the comparison is independent of the number of rows in
    the file. Differences that show up only in the last row are still
    observed, because the parsers are consumed until exhaustion.

    Because every parser is advanced in a fixed order until it is fully
    exhausted (or raises), parser errors surface in the same way and at the
    same point as when the dialects are parsed separately.

    Parameters
    ----------
    data : str
        The data of the file as a string.

    dialects : list
        The dialects to parse the data with.

    seq_pairs : dict
        Optionally maps a dialect pair (in either ordering) to the character
        sequence that the corresponding tie breaking rule inspects. For
        every differing cell of such a pair, the cell produced by the
        dialect without escape character is checked for membership of the
        sequence and the result is summarized in
        :attr:`_PairStats.all_diffs_have_seq`.

    """
    if seq_pairs is None:
        seq_pairs = {}

    parsers = [iter(parse_string(data, dialect)) for dialect in dialects]
    active = [True] * len(dialects)
    row_counts = [0] * len(dialects)

    stats: Dict[Tuple[SimpleDialect, SimpleDialect], _PairStats] = {}
    pair_indices: List[Tuple[int, int]] = []
    sequences: Dict[Tuple[int, int], Optional[str]] = {}
    # For each registered pair, the index of the dialect whose cells are
    # inspected for the sequence (the side without escape character).
    seq_sides: Dict[Tuple[int, int], int] = {}
    for i, a in enumerate(dialects):
        for j in range(i + 1, len(dialects)):
            b = dialects[j]
            pair_indices.append((i, j))
            stats[(a, b)] = _PairStats()
            if (a, b) in seq_pairs:
                sequences[(i, j)] = seq_pairs[(a, b)]
            elif (b, a) in seq_pairs:
                sequences[(i, j)] = seq_pairs[(b, a)]
            else:
                sequences[(i, j)] = None
                continue
            # The original rule inspects the cell produced without the
            # escape character.
            seq_sides[(i, j)] = i if a.escapechar == "" else j

    while any(active):
        rows: List[Optional[List[str]]] = [None] * len(dialects)
        # Advance the parsers in a fixed order so that a parser error is
        # raised at the same point as when the dialects are parsed one after
        # another.
        for i, parser in enumerate(parsers):
            if not active[i]:
                continue
            try:
                rows[i] = next(parser)
            except StopIteration:
                active[i] = False
                continue
            row_counts[i] += 1

        for i, j in pair_indices:
            pair = stats[(dialects[i], dialects[j])]
            row_x = rows[i]
            row_y = rows[j]
            if row_x is None or row_y is None:
                # One of the two parsers has no row at this position, so
                # the parsing results have different shapes.
                if row_x is not None or row_y is not None:
                    pair.same_shape = False
                    pair.same_row_count = False
                    pair.equal = False
                continue
            if len(row_x) != len(row_y):
                pair.same_shape = False
                pair.equal = False
            sequence = sequences[(i, j)]
            # Mirror the original implementation, which compares cell values
            # only for the cells that exist in both rows.
            for x, y in zip(row_x, row_y):
                if x == y:
                    continue
                pair.equal = False
                if pair.first_diff is None:
                    pair.first_diff = (x, y)
                if sequence is not None:
                    inspected = x if seq_sides[(i, j)] == i else y
                    if sequence not in inspected:
                        pair.all_diffs_have_seq = False

    # A missing row at the tail also implies a different number of rows.
    for i, j in pair_indices:
        if row_counts[i] != row_counts[j]:
            pair = stats[(dialects[i], dialects[j])]
            pair.same_shape = False
            pair.same_row_count = False
            pair.equal = False

    return stats


def _pair_stats(
    stats: Dict[Tuple[SimpleDialect, SimpleDialect], _PairStats],
    a: SimpleDialect,
    b: SimpleDialect,
) -> _PairStats:
    """Look up the summary of a pair in either ordering."""
    if (a, b) in stats:
        return stats[(a, b)]
    return stats[(b, a)]


def reduce_pairwise(
    data: str,
    dialects: List[SimpleDialect],
    stats: Optional[
        Dict[Tuple[SimpleDialect, SimpleDialect], _PairStats]
    ] = None,
) -> Optional[List[SimpleDialect]]:
    """Reduce the set of dialects by breaking pairwise ties

    Parameters
    ----------

    data: str
        The data of the file as a string

    dialects: list
        List of SimpleDialect objects

    stats: dict
        Optionally, pairwise comparison summaries produced by
        :func:`_compare_streaming` for the dialects. When supplied, the
        dialects are not parsed again.

    Returns
    -------
    dialects: list
        List of SimpleDialect objects.

    """
    equal_delim = len(set([d.delimiter for d in dialects])) == 1
    if not equal_delim:
        return None  # TODO: This might be wrong, it can just return the input!

    if stats is None:
        stats = _compare_streaming(data, dialects)

    # First, identify dialects that result in the same parsing result.
    equal_dialects = []
    for a, b in pairwise(dialects):
        if _pair_stats(stats, a, b).equal:
            equal_dialects.append((a, b))

    # Try to break the ties in these pairs
    new_dialects = set()
    visited = set()
    for A, B in equal_dialects:
        ans = break_ties_two(data, A, B, stats=stats)
        if ans is not None:
            new_dialects.add(ans)
        visited.add(A)
        visited.add(B)

    # and add the dialects that we didn't visit
    for d in dialects:
        if d not in visited:
            new_dialects.add(d)

    return list(new_dialects)


def _dialects_only_differ_in_field(
    A: SimpleDialect, B: SimpleDialect, field: str
) -> bool:
    keys = ["delimiter", "quotechar", "escapechar"]
    return all(
        getattr(A, key) == getattr(B, key) for key in keys if key != field
    )


def break_ties_two(
    data: str,
    A: SimpleDialect,
    B: SimpleDialect,
    stats: Optional[
        Dict[Tuple[SimpleDialect, SimpleDialect], _PairStats]
    ] = None,
) -> Optional[SimpleDialect]:
    """Break ties between two dialects.

    This function breaks ties between two dialects that give the same score. We
    distinguish several cases:

    1. If delimiter and escapechar are the same and one of the quote characters
    is the empty string. We parse the file with both dialects and check if the
    parsing result is the same. If it is, the correct dialect is the one with
    no quotechar, otherwise it's the other one.
    2. If quotechar and escapechar are the same and the delimiters are comma
    and space, then we go for comma. Alternatively, if either of the delimiters
    is the hyphen, we assume it's the other dialect.
    3. If the delimiter and quotechar is the same and one dialect uses the
    escapchar and the other doesn't. We break this tie by checking if the
    escapechar has an effect and if it occurs an even or odd number of times.

    If it's none of these cases, we don't break the tie and return None.

    Parameters
    ----------

    data : str
        The data of the file as a string.

    A: SimpleDialect
        A potential dialect

    B: SimpleDialect
        A potential dialect

    stats: dict
        Optionally, pairwise comparison summaries produced by
        :func:`_compare_streaming`. When supplied, the dialects are not
        parsed again.

    Returns
    -------

    dialect: SimpleDialect or None
        The chosen dialect if the tie can be broken, None otherwise.

    """
    if _dialects_only_differ_in_field(A, B, "quotechar"):
        if A.quotechar == "" or B.quotechar == "":
            d_no = A if A.quotechar == "" else B
            d_yes = B if d_no == A else A

            if stats is None:
                stats = _compare_streaming(data, [d_no, d_yes])
            pair = _pair_stats(stats, d_no, d_yes)

            if pair.equal:
                # quotechar has no effect
                return d_no
            else:
                # quotechar has an effect
                return d_yes
    elif _dialects_only_differ_in_field(A, B, "delimiter"):
        if set([A.delimiter, B.delimiter]) == set([",", " "]):
            # Artifact due to type detection (comma as radix point)
            if A.delimiter == ",":
                return A
            else:
                return B
        elif A.delimiter == "-" or B.delimiter == "-":
            # Artifact due to type detection (dash as minus sign)
            if A.delimiter == "-":
                return B
            else:
                return A
    elif _dialects_only_differ_in_field(A, B, "escapechar"):
        Dnone, Descape = (A, B) if A.escapechar == "" else (B, A)

        assert isinstance(Descape.escapechar, str)
        assert isinstance(Descape.quotechar, str)
        sequence = Descape.escapechar + Descape.quotechar
        if stats is None:
            stats = _compare_streaming(
                data,
                [Dnone, Descape],
                seq_pairs={(Dnone, Descape): sequence},
            )
        pair = _pair_stats(stats, Dnone, Descape)

        # double check shape. Usually if the shape differs the pattern score
        # should have caught it, but if by a freakish occurance it hasn't then
        # we can't break this tie (for now)
        if not pair.same_shape:
            return None
        if pair.first_diff is None:
            # The escapechar has no effect on the parsed cells.
            return None

        first_x, first_y = pair.first_diff
        # The first_diff tuple follows the ordering of the dialects in the
        # stats dictionary; pick the cell produced by the no-escape dialect.
        if (Dnone, Descape) in stats:
            unescaped_cell = first_x
        else:
            unescaped_cell = first_y
        count = _count_escaped_quotes(
            unescaped_cell, Descape.escapechar, Descape.quotechar
        )

        # We will break the ties in the following ways:
        #
        # If the escapechar precedes the quotechar an even number of times
        # within each offending cell, then we think it is a functional escape
        # and the escaped version is the correct dialect. Note that if an odd
        # number of escaped quotechars would occur, then the shape of the file
        # will be different if it is ignored. Only if it occurs an even number
        # of times within the cell can we get the same shape.
        if count > 0 and count % 2 == 0:
            return Descape
        return Dnone
    elif A.delimiter == B.delimiter:
        Aq, Ae = A.quotechar, A.escapechar
        Bq, Be = B.quotechar, B.escapechar
        if (Aq, Ae) == ("", "") or (Bq, Be) == ("", ""):
            # This case is activated if the escapechar+quotechar combination
            # occurs in the cells (i.e. "Jill\'s data") but no actual quoting
            # is done with the quote character.
            d_no = A if (Aq, Ae) == ("", "") else B
            d_yes = B if d_no == A else A

            assert isinstance(d_yes.escapechar, str)
            assert isinstance(d_yes.quotechar, str)
            sequence = d_yes.escapechar + d_yes.quotechar
            if stats is None:
                stats = _compare_streaming(
                    data,
                    [d_no, d_yes],
                    seq_pairs={(d_no, d_yes): sequence},
                )
            pair = _pair_stats(stats, d_no, d_yes)

            if not pair.same_shape:
                return None

            # if we're here, then there is no effect on structure.
            # we test if the only cells that differ are those that have an
            # escapechar+quotechar combination.
            if not pair.all_diffs_have_seq:
                return None

            # Now we know that the only cells that have the
            # escapechar+quotechar combination are the cause of the difference.
            # The right thing to do is to return the dialect that uses them.
            return d_yes

    return None


def break_ties_three(
    data: str,
    A: SimpleDialect,
    B: SimpleDialect,
    C: SimpleDialect,
    stats: Optional[
        Dict[Tuple[SimpleDialect, SimpleDialect], _PairStats]
    ] = None,
) -> Optional[SimpleDialect]:
    """Break ties between three dialects.

    If the delimiters and the escape characters are all equal, then we look for
    the dialect that has no quotechar. The tie is broken by calling
    :func:`break_ties_two` for the dialect without quotechar and another
    dialect that gives the same parsing result.

    If only the delimiter is the same for all dialects then use
    :func:`break_ties_two` on the dialects that do not have a quotechar,
    provided there are only two of these.

    Parameters
    ----------

    data: str
        The data of the file as a string

    A: SimpleDialect
        a dialect

    B: SimpleDialect
        a dialect

    C: SimpleDialect
        a dialect

    stats: dict
        Optionally, pairwise comparison summaries produced by
        :func:`_compare_streaming`. When supplied, the dialects are not
        parsed again.

    Returns
    -------

    dialect: Optional[SimpleDialect]
        The chosen dialect if the tie can be broken, None otherwise.

    Notes
    -----
    We have only observed one tie for each case during development, so
    this may need to be improved in the future.

    """
    dialects = [A, B, C]

    equal_delim = A.delimiter == B.delimiter == C.delimiter
    equal_escape = A.escapechar == B.escapechar == C.escapechar

    if equal_delim and equal_escape:
        # difference is *only* in quotechar
        if stats is None:
            stats = _compare_streaming(data, dialects)

        # The original rule only compares the number of parsed rows, not
        # the number of fields per row.
        if not all(
            _pair_stats(stats, d, other).same_row_count
            for d in dialects
            for other in dialects
            if other is not d
        ):
            return None

        d_none = next((d for d in dialects if d.quotechar == ""), None)
        if d_none is None:
            return None

        # Dialects that don't parse to exactly the same result.
        rem = [
            d
            for d in dialects
            if d is not d_none and not _pair_stats(stats, d_none, d).equal
        ]

        if len(rem) <= 1:
            # This case was reached for the file
            # 6da5ab459bcc7c3a5ed2e06d65810958.csv from the GitHub corpus of
            # the CSV paper. When fixing the delimiter to Tab, rem = [].
            # Try to reduce pairwise
            new_dialects = reduce_pairwise(data, dialects, stats=stats)
            if new_dialects is None:
                return None
            if len(new_dialects) == 1:
                return new_dialects[0]
            return None
        # With two remaining dialects both parse differently from the dialect
        # without quotechar, so the original tie can't be broken.
        return None
    elif equal_delim:
        # difference is in quotechar *and* escapechar

        # The reasoning here is as follows. If we are in this situation,
        # then there is both a potential escapechar and there are quotechars,
        # but the pattern score is the same and the type score can't make a
        # difference because no cells become clean if we interpret the
        # quote/escape correctly. This implies that the quote and escape do
        # have a function. Thus, we find the dialects that have a quote and
        # defer to break_ties_two.

        with_quote = [d for d in dialects if d.quotechar != ""]

        if len(with_quote) != 2:
            return None

        if stats is None or not (
            (with_quote[0], with_quote[1]) in stats
            or (with_quote[1], with_quote[0]) in stats
        ):
            d_no, d_yes = with_quote
            seq_pairs: Dict[Tuple[SimpleDialect, SimpleDialect], str] = {}
            escapechar = d_yes.escapechar
            quotechar = d_yes.quotechar
            if escapechar and quotechar:
                seq_pairs[(d_no, d_yes)] = escapechar + quotechar
            stats = _compare_streaming(
                data,
                with_quote,
                seq_pairs=seq_pairs,
            )
        return break_ties_two(data, with_quote[0], with_quote[1], stats=stats)

    return None


def break_ties_four(
    data: str, dialects: List[SimpleDialect]
) -> Optional[SimpleDialect]:
    """Break ties between four dialects.

    This function works by breaking the ties between pairs of dialects that
    result in the same parsing result (if any). If this reduces the number of
    dialects, then :func:`break_ties_three` or :func:`break_ties_two` is used,
    otherwise, the tie can't be broken.

    Ties are only broken if all dialects have the same delimiter.

    Parameters
    ----------

    data: str
        The data of the file as a string

    dialects: list
        List of SimpleDialect objects

    Returns
    -------
    dialect: Optional[SimpleDialect]
        The chosen dialect if the tie can be broken, None otherwise.

    Notes
    -----
    We have only observed one case during development where this
    function was needed. It may need to be revisited in the future if other
    examples are found.

    """
    # TODO: Check for length 4, handle more than 4 too?

    equal_delim = len(set([d.delimiter for d in dialects])) == 1
    if not equal_delim:
        return None

    # Register the character sequence that the escapechar tie breaking rules
    # inspect for every pair to which either rule applies, so that the
    # information is collected during the single parsing pass:
    #   * pairs that only differ in their escapechar use the sequence for the
    #     "even number of escaped quotes" rule;
    #   * pairs of a no-quote/no-escape dialect and a quote+escape dialect
    #     use the sequence for the "all differing cells contain it" rule.
    seq_pairs: Dict[Tuple[SimpleDialect, SimpleDialect], str] = {}
    for i, a in enumerate(dialects):
        for b in dialects[i + 1 :]:
            sequence: Optional[str] = None
            if _dialects_only_differ_in_field(a, b, "escapechar"):
                d_escape = a if a.escapechar != "" else b
                escapechar = d_escape.escapechar
                quotechar = d_escape.quotechar
                if escapechar and quotechar:
                    sequence = escapechar + quotechar
            elif a.delimiter == b.delimiter and (
                (a.quotechar, a.escapechar) == ("", "")
                or (b.quotechar, b.escapechar) == ("", "")
            ):
                d_yes = a if (a.quotechar, a.escapechar) != ("", "") else b
                if d_yes.quotechar and d_yes.escapechar:
                    sequence = d_yes.escapechar + d_yes.quotechar
            if sequence is not None:
                seq_pairs[(a, b)] = sequence

    stats = _compare_streaming(data, dialects, seq_pairs=seq_pairs)
    reduced_dialects = reduce_pairwise(data, dialects, stats=stats)
    if reduced_dialects is None:
        return None

    # Defer to other functions if the number of dialects was reduced
    if len(reduced_dialects) == 1:
        return reduced_dialects[0]
    elif len(reduced_dialects) == 2:
        return break_ties_two(
            data,
            reduced_dialects[0],
            reduced_dialects[1],
            stats=stats,
        )
    elif len(reduced_dialects) == 3:
        return break_ties_three(
            data,
            reduced_dialects[0],
            reduced_dialects[1],
            reduced_dialects[2],
            stats=stats,
        )

    return None
