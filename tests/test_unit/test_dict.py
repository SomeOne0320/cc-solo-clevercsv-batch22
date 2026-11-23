# -*- coding: utf-8 -*-

"""
Unit tests for the DictReader and DictWriter classes

Most of these are the same as in CPython, but we also test the cases where
CleverCSV's behavior differs.

"""

import io
import tempfile
import unittest
import warnings

from typing import Any
from typing import Dict

import clevercsv

from clevercsv.dict_read_write import DictReader


class DictTestCase(unittest.TestCase):
    ############################
    # Start tests from CPython #

    def test_writeheader_return_value(self) -> None:
        with tempfile.TemporaryFile("w+", newline="") as fp:
            writer = clevercsv.DictWriter(fp, fieldnames=["f1", "f2", "f3"])
            writeheader_return_value = writer.writeheader()
            self.assertEqual(writeheader_return_value, 10)

    def test_write_simple_dict(self) -> None:
        with tempfile.TemporaryFile("w+", newline="") as fp:
            writer = clevercsv.DictWriter(fp, fieldnames=["f1", "f2", "f3"])
            writer.writeheader()
            fp.seek(0)
            self.assertEqual(fp.readline(), "f1,f2,f3\r\n")
            writer.writerow({"f1": 10, "f3": "abc"})
            fp.seek(0)
            fp.readline()  # header
            self.assertEqual(fp.read(), "10,,abc\r\n")

    def test_write_multiple_dict_rows(self) -> None:
        fp = io.StringIO()
        writer = clevercsv.DictWriter(fp, fieldnames=["f1", "f2", "f3"])
        writer.writeheader()
        self.assertEqual(fp.getvalue(), "f1,f2,f3\r\n")
        writer.writerows(
            [
                {"f1": 1, "f2": "abc", "f3": "f"},
                {"f1": 2, "f2": 5, "f3": "xyz"},
            ]
        )
        self.assertEqual(fp.getvalue(), "f1,f2,f3\r\n1,abc,f\r\n2,5,xyz\r\n")

    def test_write_no_fields(self) -> None:
        fp = io.StringIO()
        self.assertRaises(TypeError, clevercsv.DictWriter, fp)

    def test_write_fields_not_in_fieldnames(self) -> None:
        with tempfile.TemporaryFile("w+", newline="") as fp:
            writer = clevercsv.DictWriter(fp, fieldnames=["f1", "f2", "f3"])
            # Of special note is the non-string key (CPython issue 19449)
            content: Dict[Any, Any] = {"f4": 10, "f2": "spam", 1: "abc"}
            with self.assertRaises(ValueError) as cx:
                writer.writerow(content)
            exception = str(cx.exception)
            self.assertIn("fieldnames", exception)
            self.assertIn("'f4'", exception)
            self.assertNotIn("'f2'", exception)
            self.assertIn("1", exception)

    def test_typo_in_extrasaction_raises_error(self) -> None:
        fp = io.StringIO()
        self.assertRaises(
            ValueError,
            clevercsv.DictWriter,
            fp,
            ["f1", "f2"],
            extrasaction="raised",
        )

    def test_write_field_not_in_field_names_raise(self) -> None:
        fp = io.StringIO()
        writer = clevercsv.DictWriter(fp, ["f1", "f2"], extrasaction="raise")
        dictrow = {"f0": 0, "f1": 1, "f2": 2, "f3": 3}
        self.assertRaises(
            ValueError, clevercsv.DictWriter.writerow, writer, dictrow
        )

    def test_write_field_not_in_field_names_ignore(self) -> None:
        fp = io.StringIO()
        writer = clevercsv.DictWriter(fp, ["f1", "f2"], extrasaction="ignore")
        dictrow = {"f0": 0, "f1": 1, "f2": 2, "f3": 3}
        clevercsv.DictWriter.writerow(writer, dictrow)
        self.assertEqual(fp.getvalue(), "1,2\r\n")

    def test_read_dict_fields(self) -> None:
        with tempfile.TemporaryFile("w+") as fp:
            fp.write("1,2,abc\r\n")
            fp.seek(0)
            reader: DictReader[str] = clevercsv.DictReader(
                fp, fieldnames=["f1", "f2", "f3"]
            )
            self.assertEqual(next(reader), {"f1": "1", "f2": "2", "f3": "abc"})

    def test_read_dict_no_fieldnames(self) -> None:
        with tempfile.TemporaryFile("w+") as fp:
            fp.write("f1,f2,f3\r\n1,2,abc\r\n")
            fp.seek(0)
            reader: DictReader[str] = clevercsv.DictReader(fp)
            self.assertEqual(next(reader), {"f1": "1", "f2": "2", "f3": "abc"})
            self.assertEqual(reader.fieldnames, ["f1", "f2", "f3"])

    # Two test cases to make sure existing ways of implicitly setting
    # fieldnames continue to work.  Both arise from discussion in issue3436.
    def test_read_dict_fieldnames_from_file(self) -> None:
        with tempfile.TemporaryFile("w+") as fp:
            fp.write("f1,f2,f3\r\n1,2,abc\r\n")
            fp.seek(0)
            reader: DictReader[str] = clevercsv.DictReader(
                fp, fieldnames=next(clevercsv.reader(fp))
            )
            self.assertEqual(reader.fieldnames, ["f1", "f2", "f3"])
            self.assertEqual(next(reader), {"f1": "1", "f2": "2", "f3": "abc"})

    def test_read_dict_fieldnames_chain(self) -> None:
        import itertools

        with tempfile.TemporaryFile("w+") as fp:
            fp.write("f1,f2,f3\r\n1,2,abc\r\n")
            fp.seek(0)
            reader: DictReader[str] = clevercsv.DictReader(fp)
            first = next(reader)
            for row in itertools.chain([first], reader):
                self.assertEqual(reader.fieldnames, ["f1", "f2", "f3"])
                self.assertEqual(row, {"f1": "1", "f2": "2", "f3": "abc"})

    def test_read_long(self) -> None:
        with tempfile.TemporaryFile("w+") as fp:
            fp.write("1,2,abc,4,5,6\r\n")
            fp.seek(0)
            reader = clevercsv.DictReader(fp, fieldnames=["f1", "f2"])
            self.assertEqual(
                next(reader),
                {"f1": "1", "f2": "2", None: ["abc", "4", "5", "6"]},
            )

    def test_read_long_with_rest(self) -> None:
        with tempfile.TemporaryFile("w+") as fp:
            fp.write("1,2,abc,4,5,6\r\n")
            fp.seek(0)
            reader = clevercsv.DictReader(
                fp, fieldnames=["f1", "f2"], restkey="_rest"
            )
            self.assertEqual(
                next(reader),
                {"f1": "1", "f2": "2", "_rest": ["abc", "4", "5", "6"]},
            )

    def test_read_long_with_rest_no_fieldnames(self) -> None:
        with tempfile.TemporaryFile("w+") as fp:
            fp.write("f1,f2\r\n1,2,abc,4,5,6\r\n")
            fp.seek(0)
            reader: DictReader[str] = clevercsv.DictReader(fp, restkey="_rest")
            self.assertEqual(reader.fieldnames, ["f1", "f2"])
            self.assertEqual(
                next(reader),
                {"f1": "1", "f2": "2", "_rest": ["abc", "4", "5", "6"]},
            )

    def test_read_short(self) -> None:
        with tempfile.TemporaryFile("w+") as fp:
            fp.write("1,2,abc,4,5,6\r\n1,2,abc\r\n")
            fp.seek(0)
            reader = clevercsv.DictReader(
                fp, fieldnames="1 2 3 4 5 6".split(), restval="DEFAULT"
            )
            self.assertEqual(
                next(reader),
                {"1": "1", "2": "2", "3": "abc", "4": "4", "5": "5", "6": "6"},
            )
            self.assertEqual(
                next(reader),
                {
                    "1": "1",
                    "2": "2",
                    "3": "abc",
                    "4": "DEFAULT",
                    "5": "DEFAULT",
                    "6": "DEFAULT",
                },
            )

    def test_read_multi(self) -> None:
        sample = [
            "2147483648,43.0e12,17,abc,def\r\n",
            "147483648,43.0e2,17,abc,def\r\n",
            "47483648,43.0,170,abc,def\r\n",
        ]

        reader = clevercsv.DictReader(
            sample, fieldnames="i1 float i2 s1 s2".split()
        )
        self.assertEqual(
            next(reader),
            {
                "i1": "2147483648",
                "float": "43.0e12",
                "i2": "17",
                "s1": "abc",
                "s2": "def",
            },
        )

    def test_read_with_blanks(self) -> None:
        reader = clevercsv.DictReader(
            ["1,2,abc,4,5,6\r\n", "\r\n", "1,2,abc,4,5,6\r\n"],
            fieldnames="1 2 3 4 5 6".split(),
        )
        self.assertEqual(
            next(reader),
            {"1": "1", "2": "2", "3": "abc", "4": "4", "5": "5", "6": "6"},
        )
        self.assertEqual(
            next(reader),
            {"1": "1", "2": "2", "3": "abc", "4": "4", "5": "5", "6": "6"},
        )

    def test_read_semi_sep(self) -> None:
        reader = clevercsv.DictReader(
            ["1;2;abc;4;5;6\r\n"],
            fieldnames="1 2 3 4 5 6".split(),
            delimiter=";",
        )
        self.assertEqual(
            next(reader),
            {"1": "1", "2": "2", "3": "abc", "4": "4", "5": "5", "6": "6"},
        )

    # End tests from CPython #
    ##########################

    ###################################
    # Start tests added for CleverCSV #

    def test_read_duplicate_fieldnames(self) -> None:
        reader: DictReader[str] = clevercsv.DictReader(
            ["f1,f2,f1\r\n", "a", "b", "c"]
        )
        with self.assertWarns(UserWarning):
            reader.fieldnames

    def test_read_empty_file_fieldnames_returns_none(self) -> None:
        # Accessing .fieldnames on an empty file should return None (matching
        # stdlib csv.DictReader behaviour), not raise AssertionError.
        reader: DictReader[str] = clevercsv.DictReader(io.StringIO(""))
        self.assertIsNone(reader.fieldnames)

    def test_read_empty_file_iteration_raises_stopiteration(self) -> None:
        # Iterating over an empty file should raise StopIteration, not
        # AssertionError.
        reader: DictReader[str] = clevercsv.DictReader(io.StringIO(""))
        with self.assertRaises(StopIteration):
            next(reader)

    # End tests added for CleverCSV #
    #################################

    ############################
    # Tests for columns mapping

    def test_columns_duplicate_headers_with_occurrence(self) -> None:
        # The motivating use case: two headers named "金额" must both be
        # reachable instead of one overwriting the other.
        data = "branch,amount,amount,note\r\nA,100,10,ok\r\nB,,20,x\r\n"
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO(data),
            columns={
                "branch": "branch",
                "gross": ("amount", 1),
                "refund": ("amount", 2),
            },
        )
        self.assertEqual(
            reader.fieldnames, ["branch", "gross", "refund"]
        )
        self.assertEqual(
            next(reader),
            {"branch": "A", "gross": "100", "refund": "10"},
        )
        self.assertEqual(
            next(reader),
            {"branch": "B", "gross": "", "refund": "20"},
        )

    def test_columns_unique_name_and_output_order(self) -> None:
        # A bare name works when unique, and the output order follows the
        # mapping rather than the header order.
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,b,c\r\n1,2,3\r\n"),
            columns={"z": "c", "x": "a"},
        )
        self.assertEqual(list(reader), [{"z": "3", "x": "1"}])

    def test_columns_ambiguous_bare_name_raises(self) -> None:
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,a\r\n1,2\r\n"), columns={"x": "a"}
        )
        with self.assertRaises(ValueError):
            next(reader)

    def test_columns_missing_column_raises_at_header(self) -> None:
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,b\r\n1,2\r\n3,4\r\n"),
            columns={"x": "missing"},
        )
        # The error is raised while reading the header; accessing fieldnames
        # directly must raise too.
        with self.assertRaises(ValueError):
            reader.fieldnames
        # And no data row may have been delivered.
        with self.assertRaises(ValueError):
            next(reader)

    def test_columns_error_delivers_no_rows(self) -> None:
        # Even when the first mapping entry is valid, a bad later entry must
        # abort before any data row is yielded.
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,b\r\n1,2\r\n"),
            columns={"ok": "a", "bad": "nope"},
        )
        self.assertRaises(ValueError, list, reader)

    def test_columns_occurrence_out_of_range(self) -> None:
        cases = [("a", 0), ("a", 3)]
        for selector in cases:
            with self.subTest(selector=selector):
                reader: DictReader[str] = clevercsv.DictReader(
                    io.StringIO("a,a\r\n1,2\r\n"),
                    columns={"x": selector},
                )
                with self.assertRaises(ValueError):
                    next(reader)

    def test_columns_non_mapping_raises_type_error(self) -> None:
        with self.assertRaises(TypeError):
            clevercsv.DictReader(
                io.StringIO("a\r\n1\r\n"),
                columns=["a"],  # type: ignore[arg-type]
            )

    def test_columns_short_rows_use_restval_without_shifting(self) -> None:
        # Missing trailing values in an old-style short row must be filled with
        # restval; later columns must never receive values shifted forward.
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,b,c\r\n1,2\r\n"),
            restval="MISSING",
            columns={"A": "a", "B": "b", "C": "c"},
        )
        self.assertEqual(
            list(reader),
            [{"A": "1", "B": "2", "C": "MISSING"}],
        )

        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,b,c\r\n1\r\n"),
            columns={"A": "a", "C": "c"},
        )
        self.assertEqual(
            list(reader),
            [{"A": "1", "C": None}],
        )

    def test_columns_long_rows_use_restkey(self) -> None:
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,b\r\n1,2,3,4\r\n"),
            restkey="_rest",
            columns={"A": "a"},
        )
        self.assertEqual(
            next(reader),
            {"A": "1", "_rest": ["3", "4"]},
        )

    def test_columns_quoted_newline_not_split(self) -> None:
        source = iter(['a,b\r\n', '"line1\r\nline2",x\r\n', 'y,z\r\n'])
        reader: DictReader[str] = clevercsv.DictReader(
            source, columns={"A": "a"}
        )
        self.assertEqual(next(reader), {"A": "line1\r\nline2"})
        self.assertEqual(next(reader), {"A": "y"})

    def test_columns_with_explicit_fieldnames(self) -> None:
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("1,2\r\n"),
            fieldnames=["f1", "f2"],
            columns={"out": "f2"},
        )
        self.assertEqual(reader.fieldnames, ["out"])
        self.assertEqual(list(reader), [{"out": "2"}])

    def test_columns_fieldnames_setter_overrides_mapping(self) -> None:
        # Explicitly assigning fieldnames is the stdlib escape hatch and must
        # take precedence over a columns mapping. As in stdlib, the first row
        # is then consumed as a data row.
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,b\r\n1,2\r\n"), columns={"x": "a"}
        )
        reader.fieldnames = ["p", "q"]
        self.assertEqual(next(reader), {"p": "a", "q": "b"})
        self.assertEqual(next(reader), {"p": "1", "q": "2"})

    def test_columns_suppresses_duplicate_fieldnames_warning(self) -> None:
        # With columns, duplicate headers are explicitly handled, so the
        # "columns will be dropped" warning doesn't apply.
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,a\r\n1,2\r\n"),
            columns={"x": ("a", 1), "y": ("a", 2)},
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            reader.fieldnames
        self.assertEqual(
            next(reader), {"x": "1", "y": "2"}
        )

    def test_columns_empty_file_fieldnames_none(self) -> None:
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO(""), columns={"x": "a"}
        )
        self.assertIsNone(reader.fieldnames)
        with self.assertRaises(StopIteration):
            next(reader)

    def test_columns_default_behavior_unchanged(self) -> None:
        reader: DictReader[str] = clevercsv.DictReader(
            io.StringIO("a,b\r\n1,2\r\n")
        )
        self.assertEqual(reader.fieldnames, ["a", "b"])
        self.assertEqual(next(reader), {"a": "1", "b": "2"})


if __name__ == "__main__":
    unittest.main()
