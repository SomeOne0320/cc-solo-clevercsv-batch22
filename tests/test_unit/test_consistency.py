# -*- coding: utf-8 -*-

"""
Unit test for consistency score

Author: G.J.J. van den Burg

"""

import unittest

from unittest import mock

from typing import Any
from typing import Dict

import clevercsv

from clevercsv import consistency
from clevercsv.break_ties import tie_breaker
from clevercsv.consistency import ConsistencyDetector
from clevercsv.consistency import ConsistencyScore
from clevercsv.cparser_util import parse_data
from clevercsv.dialect import SimpleDialect
from clevercsv.potential_dialects import get_dialects


class ConsistencyTestCase(unittest.TestCase):
    def test_get_best_set_1(self) -> None:
        scores = {
            SimpleDialect(",", None, None): ConsistencyScore(P=1, T=1, Q=1),
            SimpleDialect(";", None, None): ConsistencyScore(
                P=1, T=None, Q=None
            ),
            SimpleDialect("|", None, None): ConsistencyScore(P=2, T=1, Q=2),
        }
        H = ConsistencyDetector.get_best_dialects(scores)
        self.assertEqual(H, [SimpleDialect("|", None, None)])


class DetectionFieldLimitTestCase(unittest.TestCase):
    """The field limit used during detection is local to the detection"""

    def setUp(self) -> None:
        self.limit = clevercsv.field_size_limit()
        clevercsv.field_size_limit(10)

    def tearDown(self) -> None:
        clevercsv.field_size_limit(self.limit)

    def test_detect_long_field(self) -> None:
        # A field may be much longer than the global limit. Detection should
        # still succeed, while the global limit is left untouched.
        data = "a," + "X" * 500 + "\nc,d\n"

        dialects = get_dialects(data)
        scores = ConsistencyDetector().compute_consistency_scores(
            data, dialects, field_limit=len(data) + 1
        )
        self.assertEqual(
            ConsistencyDetector.get_best_dialects(scores),
            [SimpleDialect(",", "", "")],
        )

        result = ConsistencyDetector().detect(data)
        self.assertEqual(result, SimpleDialect(",", "", ""))
        self.assertEqual(clevercsv.field_size_limit(), 10)

        # The public parsing entry point still respects the global limit.
        with self.assertRaises(clevercsv.Error):
            list(parse_data([data], delimiter=",", quotechar=""))

    def test_detect_reports_limit_while_running(self) -> None:
        # Detection must not modify the global limit, not even temporarily.
        data = "a," + "X" * 500 + "\nc,d\n"
        seen = []

        original = consistency.parse_string

        def wrapped(*args, **kwargs):
            seen.append(clevercsv.field_size_limit())
            yield from original(*args, **kwargs)

        with mock.patch.object(consistency, "parse_string", wrapped):
            result = ConsistencyDetector().detect(data)

        self.assertEqual(result, SimpleDialect(",", "", ""))
        self.assertTrue(seen)
        self.assertEqual(seen, [10] * len(seen))
        self.assertEqual(clevercsv.field_size_limit(), 10)


class DetectionTieBreakFieldLimitTestCase(unittest.TestCase):
    """Re-parsing tied candidates uses the detection's own field limit"""

    # These dialects tie on the consistency score and are only distinguished
    # by comparing their parsing results in the tie breaker.
    data = 'a,"b"c\nc,' + "X" * 500 + "\n"

    def setUp(self) -> None:
        self.limit = clevercsv.field_size_limit()
        clevercsv.field_size_limit(10)

    def tearDown(self) -> None:
        clevercsv.field_size_limit(self.limit)

    def _tied_dialects(self):
        scores = ConsistencyDetector().compute_consistency_scores(
            self.data, get_dialects(self.data), field_limit=len(self.data) + 1
        )
        best = ConsistencyDetector.get_best_dialects(scores)
        self.assertEqual(
            best,
            [SimpleDialect(",", "", ""), SimpleDialect(",", '"', "")],
        )
        return best

    def test_tie_break_uses_local_limit(self) -> None:
        best = self._tied_dialects()

        # Re-parsing the candidates with the global limit can't work, which
        # shows that the tie breaker really compares parsing results.
        with self.assertRaises(clevercsv.Error):
            tie_breaker(self.data, best)

        result = ConsistencyDetector().detect(self.data)
        self.assertEqual(result, SimpleDialect(",", "", ""))
        self.assertEqual(clevercsv.field_size_limit(), 10)

    def test_tie_break_escapechar_uses_local_limit(self) -> None:
        data = 'a,b\\"c\nc,' + "X" * 500 + "\n"
        result = ConsistencyDetector().detect(data)
        self.assertEqual(result, SimpleDialect(",", '"', "\\"))
        self.assertEqual(clevercsv.field_size_limit(), 10)


class DetectionConcurrentReaderTestCase(unittest.TestCase):
    """A reader started during detection uses the public field size limit"""

    def setUp(self) -> None:
        self.limit = clevercsv.field_size_limit()
        clevercsv.field_size_limit(10)

    def tearDown(self) -> None:
        clevercsv.field_size_limit(self.limit)

    def test_reader_and_detection_interleaved(self) -> None:
        long_data = "a," + "X" * 500 + "\nc,d\n"
        short_data = "e;f\ng;h\n"
        results: Dict[str, Any] = {}

        original = consistency.parse_string
        ran = [False]

        def wrapped(*args, **kwargs):
            if not ran[0]:
                ran[0] = True
                # Simulate another import starting a reader while the
                # detection is still parsing its candidates.
                try:
                    list(clevercsv.reader(["a," + "X" * 500]))
                except clevercsv.Error as err:
                    results["reader_error"] = str(err)
                results["short"] = list(clevercsv.reader(["a,b", "c,d"]))
                results["limit_during"] = clevercsv.field_size_limit()
                # A nested detection only sees its own sample.
                results["nested"] = ConsistencyDetector().detect(short_data)
            yield from original(*args, **kwargs)

        with mock.patch.object(consistency, "parse_string", wrapped):
            result = ConsistencyDetector().detect(long_data)

        self.assertEqual(result, SimpleDialect(",", "", ""))
        self.assertEqual(results["short"], [["a", "b"], ["c", "d"]])
        self.assertIn(
            "field larger than field limit (10)", results["reader_error"]
        )
        self.assertEqual(results["limit_during"], 10)
        self.assertEqual(results["nested"], SimpleDialect(";", "", ""))
        self.assertEqual(clevercsv.field_size_limit(), 10)

    def test_detection_failure_leaves_limit_unchanged(self) -> None:
        data = "a,b\0c\nd,e\n"
        with self.assertRaises(clevercsv.Error):
            ConsistencyDetector().detect(data)
        self.assertEqual(clevercsv.field_size_limit(), 10)

        # Detection after the failed attempt is unaffected.
        with self.assertRaises(clevercsv.Error):
            list(clevercsv.reader(["a," + "X" * 500]))
        self.assertEqual(clevercsv.field_size_limit(), 10)
