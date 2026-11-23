# -*- coding: utf-8 -*-

"""
Unit tests for the dialect tie breaking.

These tests focus on the behaviors that the streaming tie breaker must
preserve: identical and different parsing results, row/column shapes, the
effect of quoting and escaping, parser errors, and differences that only
appear near the end of the file.

Author: Gertjan van den Burg

"""

import gc
import unittest

from typing import List

from clevercsv import field_size_limit
from clevercsv.break_ties import _compare_streaming
from clevercsv.break_ties import break_ties_four
from clevercsv.break_ties import break_ties_three
from clevercsv.break_ties import break_ties_two
from clevercsv.break_ties import reduce_pairwise
from clevercsv.cparser_util import parse_string
from clevercsv.dialect import SimpleDialect
from clevercsv.exceptions import Error


class BreakTiesTwoTestCase(unittest.TestCase):
    def test_quotechar_no_effect(self) -> None:
        data = "a,b,c\n1,2,3\n"
        d_no = SimpleDialect(",", "", "")
        d_yes = SimpleDialect(",", '"', "")
        self.assertEqual(break_ties_two(data, d_no, d_yes), d_no)
        # argument order must not matter
        self.assertEqual(break_ties_two(data, d_yes, d_no), d_no)

    def test_quotechar_effect(self) -> None:
        data = 'a,b,c\n1,2,"x,y"\n'
        d_no = SimpleDialect(",", "", "")
        d_yes = SimpleDialect(",", '"', "")
        self.assertEqual(break_ties_two(data, d_no, d_yes), d_yes)
        self.assertEqual(break_ties_two(data, d_yes, d_no), d_yes)

    def test_quotechar_effect_only_in_last_row(self) -> None:
        prefix = "1,2,3\n" * 1000
        d_no = SimpleDialect(",", "", "")
        d_yes = SimpleDialect(",", '"', "")

        same = prefix + "4,5,6\n"
        self.assertEqual(break_ties_two(same, d_no, d_yes), d_no)

        different = prefix + '4,"5,6"\n'
        self.assertEqual(break_ties_two(different, d_no, d_yes), d_yes)

    def test_delimiter_comma_space(self) -> None:
        data = "a b c\n1 2 3\n"
        d_comma = SimpleDialect(",", "", "")
        d_space = SimpleDialect(" ", "", "")
        self.assertEqual(break_ties_two(data, d_comma, d_space), d_comma)
        self.assertEqual(break_ties_two(data, d_space, d_comma), d_comma)

    def test_delimiter_hyphen(self) -> None:
        data = "2020-01-01\n2021-12-31\n"
        d_dash = SimpleDialect("-", "", "")
        d_comma = SimpleDialect(",", "", "")
        self.assertEqual(break_ties_two(data, d_dash, d_comma), d_comma)
        self.assertEqual(break_ties_two(data, d_comma, d_dash), d_comma)

    def test_escapechar_even_count(self) -> None:
        d_none = SimpleDialect(",", "'", "")
        d_escape = SimpleDialect(",", "'", "\\")
        data = r"a,b" + "\n" + r"1,x\'y\'z" + "\n"
        self.assertEqual(break_ties_two(data, d_none, d_escape), d_escape)
        self.assertEqual(break_ties_two(data, d_escape, d_none), d_escape)

    def test_escapechar_odd_count(self) -> None:
        d_none = SimpleDialect(",", "'", "")
        d_escape = SimpleDialect(",", "'", "\\")
        data = r"a,b" + "\n" + r"1,x\'y" + "\n"
        self.assertEqual(break_ties_two(data, d_none, d_escape), d_none)

    def test_escapechar_no_effect(self) -> None:
        d_none = SimpleDialect(",", "'", "")
        d_escape = SimpleDialect(",", "'", "\\")
        data = "a,b\n1,plain\n"
        self.assertIsNone(break_ties_two(data, d_none, d_escape))

    def test_escapechar_shape_difference_rows(self) -> None:
        d_none = SimpleDialect(",", "'", "")
        d_escape = SimpleDialect(",", "'", "\\")
        data = "a,b\n'x\\',y\nz,w\n"
        # the two parsers produce a different number of rows
        self.assertNotEqual(
            len(list(parse_string(data, d_none))),
            len(list(parse_string(data, d_escape))),
        )
        self.assertIsNone(break_ties_two(data, d_none, d_escape))

    def test_escapechar_shape_difference_fields(self) -> None:
        d_none = SimpleDialect(",", "'", "")
        d_escape = SimpleDialect(",", "'", "\\")
        # same number of rows, but a row has a different number of fields
        data = "a,b,c\n1,2,3\n4,5\n6,7,8\n"
        parsed_none = list(parse_string(data, d_none))
        parsed_escape = list(parse_string(data, d_escape))
        self.assertEqual(len(parsed_none), len(parsed_escape))
        self.assertIsNone(break_ties_two(data, d_none, d_escape))

    def test_quote_and_escape_vs_nothing(self) -> None:
        d_no = SimpleDialect(",", "", "")
        d_yes = SimpleDialect(",", "'", "\\")

        data = r"a,b" + "\n" + r"1,Jill\'s" + "\n"
        self.assertEqual(break_ties_two(data, d_no, d_yes), d_yes)

        # when the only difference comes from quoting without the
        # escapechar+quotechar combination, the tie can't be broken this way
        data_quoted = "a,b\n'quoted',y\n"
        self.assertIsNone(break_ties_two(data_quoted, d_no, d_yes))

        # identical parsing results still select the dialect that uses them
        data_same = "a,b\n1,plaindiff\n"
        self.assertEqual(break_ties_two(data_same, d_no, d_yes), d_yes)

    def test_empty_data(self) -> None:
        d_no = SimpleDialect(",", "", "")
        d_yes = SimpleDialect(",", '"', "")
        self.assertEqual(break_ties_two("", d_no, d_yes), d_no)
        self.assertEqual(break_ties_two("\n", d_no, d_yes), d_no)

    def test_strict_error_propagates(self) -> None:
        d_quote = SimpleDialect(",", '"', "", strict=True)
        d_no = SimpleDialect(",", "", "", strict=True)
        data = 'a,b\n"x"y,z\n'
        with self.assertRaises(Error):
            break_ties_two(data, d_quote, d_no)
        with self.assertRaises(Error):
            break_ties_two(data, d_no, d_quote)

    def test_field_limit_error_propagates(self) -> None:
        d_no = SimpleDialect(",", "", "")
        d_yes = SimpleDialect(",", '"', "")
        data = "a,b\n" + "x" * 50 + ",y\n"
        old_limit = field_size_limit(10)
        try:
            with self.assertRaises(Error):
                break_ties_two(data, d_no, d_yes)
        finally:
            field_size_limit(old_limit)


class BreakTiesThreeTestCase(unittest.TestCase):
    def test_identical_parsing(self) -> None:
        data = "a,b,c\n1,2,3\n4,5,6\n"
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(",", '"', ""),
            SimpleDialect(",", "'", ""),
        ]
        self.assertEqual(break_ties_three(data, *dialects), dialects[0])

    def test_difference_only_in_last_row(self) -> None:
        prefix = "1,2,3\n" * 500
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(",", '"', ""),
            SimpleDialect(",", "'", ""),
        ]
        same = prefix + "4,5,6\n"
        self.assertEqual(break_ties_three(same, *dialects), dialects[0])
        different = prefix + '4,"5,6"\n'
        self.assertIsNone(break_ties_three(different, *dialects))

    def test_shape_difference(self) -> None:
        data = "a,b\n1,2\n3,4\n"
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(",", '"', ""),
            SimpleDialect(",", "'", ""),
        ]
        # force a shape difference through quoting in the last row
        data = data + '5,"6,7"\n'
        self.assertIsNone(break_ties_three(data, *dialects))

    def test_field_count_difference_keeps_row_count_rule(self) -> None:
        # The three-dialect rule only looks at the number of rows; a
        # difference in the number of fields per row must not be mistaken
        # for a row-count difference.
        data = 'a,b\n"x,y",z\n'
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(",", '"', ""),
            SimpleDialect(",", "'", ""),
        ]
        parsed = [list(parse_string(data, d)) for d in dialects]
        self.assertEqual({len(p) for p in parsed}, {2})
        self.assertNotEqual(
            [len(r) for r in parsed[0]],
            [len(r) for r in parsed[1]],
        )
        stats = _compare_streaming(data, dialects)
        self.assertTrue(all(pair.same_row_count for pair in stats.values()))
        self.assertTrue(any(not pair.same_shape for pair in stats.values()))
        # the decision still follows the original rule
        self.assertIsNone(break_ties_three(data, *dialects))

    def test_quote_and_escape_branch(self) -> None:
        # equal delimiter, differing quotechar and escapechar: the two
        # dialects with a quotechar defer to break_ties_two, where the
        # escapechar-only rule selects the dialect using the escapechar.
        data = r"a,b" + "\n" + r"1,x\'y\'z" + "\n"
        d_none = SimpleDialect(",", "", "")
        d_escape = SimpleDialect(",", "'", "\\")
        d_quote = SimpleDialect(",", "'", "")
        result = break_ties_three(data, d_none, d_escape, d_quote)
        self.assertEqual(result, d_escape)


class BreakTiesFourTestCase(unittest.TestCase):
    def test_identical_parsing(self) -> None:
        data = "a,b,c\n1,2,3\n4,5,6\n"
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(",", '"', ""),
            SimpleDialect(",", "'", ""),
            SimpleDialect(",", "~", ""),
        ]
        self.assertEqual(break_ties_four(data, dialects), dialects[0])

    def test_identical_parsing_large_file(self) -> None:
        data = "x,y,z\n" * 10000
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(",", '"', ""),
            SimpleDialect(",", "'", ""),
            SimpleDialect(",", "~", ""),
        ]
        self.assertEqual(break_ties_four(data, dialects), dialects[0])

    def test_different_delimiters_not_broken(self) -> None:
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(";", '"', ""),
            SimpleDialect("|", "'", ""),
            SimpleDialect("\t", "~", ""),
        ]
        self.assertIsNone(break_ties_four("a,b\n1,2\n", dialects))

    def test_escape_pair_reduced(self) -> None:
        # The dialect with the functional escape is the only one that drops
        # the backslash; the other three dialects parse the file identically.
        # Pairwise reduction therefore keeps the escape dialect next to a
        # no-quote dialect and the escape rule settles the tie.
        data = "123\n" + r"Jill\'s data"
        dialects = [
            SimpleDialect(",", "'", "\\"),
            SimpleDialect(",", "'", ""),
            SimpleDialect(",", "", ""),
            SimpleDialect(",", "", "\\"),
        ]
        parsed = {d: list(parse_string(data, d)) for d in dialects}
        self.assertEqual(
            parsed[dialects[1]],
            parsed[dialects[2]],
        )
        self.assertEqual(
            parsed[dialects[2]],
            parsed[dialects[3]],
        )
        self.assertNotEqual(parsed[dialects[0]], parsed[dialects[1]])
        self.assertEqual(
            break_ties_four(data, dialects),
            SimpleDialect(",", "'", "\\"),
        )

    def test_reduce_pairwise_matches_parses(self) -> None:
        data = "a,b,c\n1,2,3\n"
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(",", '"', ""),
            SimpleDialect(",", "'", ""),
            SimpleDialect(",", "~", ""),
        ]
        reduced = reduce_pairwise(data, dialects)
        self.assertEqual(reduced, [SimpleDialect(",", "", "")])


class StreamingComparisonTestCase(unittest.TestCase):
    def test_each_dialect_parsed_once(self) -> None:
        import clevercsv.break_ties as break_ties_module

        data = "a,b\n1,2\n3,4\n"
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(",", '"', ""),
            SimpleDialect(",", "'", ""),
            SimpleDialect(",", "~", ""),
        ]
        counts = {}
        original = break_ties_module.parse_string

        def counting_parse(d, dialect, return_quoted=False):
            counts[dialect] = counts.get(dialect, 0) + 1
            return original(d, dialect, return_quoted=return_quoted)

        break_ties_module.parse_string = counting_parse
        try:
            break_ties_four(data, dialects)
        finally:
            break_ties_module.parse_string = original
        self.assertEqual(set(counts.values()), {1})
        self.assertEqual(set(counts), set(dialects))

    def test_summary_is_independent_of_number_of_rows(self) -> None:
        dialects = [
            SimpleDialect(",", "", ""),
            SimpleDialect(",", '"', ""),
        ]
        sizes: List[int] = []
        for nrows in (10, 10_000, 100_000):
            data = "1,2,3\n" * nrows
            gc.collect()
            before = len(gc.get_objects())
            stats = _compare_streaming(data, dialects)
            after = len(gc.get_objects())
            del stats
            gc.collect()
            sizes.append(after - before)
        # the summaries retain a fixed amount of information, so the number
        # of tracked objects must not grow with the number of rows
        self.assertLessEqual(max(sizes), 25)
        self.assertEqual(max(sizes) - min(sizes), 0)

    def test_tail_difference_is_observed(self) -> None:
        d_no = SimpleDialect(",", "", "")
        d_yes = SimpleDialect(",", '"', "")
        # quoting merges two fields into one in the very last row
        data = ("1,2,3\n" * 5000) + '"1,2",3\n'
        no_rows = list(parse_string(data, d_no))
        yes_rows = list(parse_string(data, d_yes))
        self.assertEqual(len(no_rows), len(yes_rows))
        self.assertNotEqual(no_rows[-1], yes_rows[-1])
        stats = _compare_streaming(data, [d_no, d_yes])
        pair = stats[(d_no, d_yes)]
        self.assertFalse(pair.equal)
        self.assertFalse(pair.same_shape)
        self.assertIsNotNone(pair.first_diff)

    def test_tail_difference_same_shape_is_observed(self) -> None:
        d_no = SimpleDialect(",", "", "")
        d_yes = SimpleDialect(",", '"', "")
        # quoting changes a cell value but keeps the row and field counts
        data = ("1,2,3\n" * 5000) + '4,"5",6\n'
        no_rows = list(parse_string(data, d_no))
        yes_rows = list(parse_string(data, d_yes))
        self.assertEqual(len(no_rows), len(yes_rows))
        self.assertEqual([len(r) for r in no_rows], [len(r) for r in yes_rows])
        self.assertNotEqual(no_rows, yes_rows)
        stats = _compare_streaming(data, [d_no, d_yes])
        pair = stats[(d_no, d_yes)]
        self.assertFalse(pair.equal)
        self.assertTrue(pair.same_shape)
        self.assertIsNotNone(pair.first_diff)

    def test_row_count_difference_recorded(self) -> None:
        d_none = SimpleDialect(",", "'", "")
        d_escape = SimpleDialect(",", "'", "\\")
        data = "a,b\n'x\\',y\nz,w\n"
        self.assertNotEqual(
            len(list(parse_string(data, d_none))),
            len(list(parse_string(data, d_escape))),
        )
        stats = _compare_streaming(data, [d_none, d_escape])
        pair = stats[(d_none, d_escape)]
        self.assertFalse(pair.same_shape)
        self.assertFalse(pair.same_row_count)
        self.assertFalse(pair.equal)


if __name__ == "__main__":
    unittest.main()
