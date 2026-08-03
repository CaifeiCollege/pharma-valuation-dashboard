import math
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from valuation import (  # noqa: E402
    calculate_percentile,
    classify_percentile,
    filter_history,
    validate_index_record,
)


class ValuationTests(unittest.TestCase):
    def test_percentile_counts_values_at_or_below_current(self):
        self.assertEqual(calculate_percentile([10.0, 20.0, 20.0, 40.0], 20.0), 75.0)

    def test_filter_removes_pre_cutoff_and_invalid_values(self):
        points = [
            ("2015-01-01", 9),
            ("2017-01-01", None),
            ("2020-01-01", -2),
            ("2026-01-01", 31.5),
            ("bad-date", 20),
            ("2026-02-01", math.inf),
        ]
        self.assertEqual(
            filter_history(points, date(2016, 1, 1)),
            [("2026-01-01", 31.5)],
        )

    def test_history_after_cutoff_is_retained_from_inception(self):
        points = [("2023-01-01", 28), ("2024-01-01", 32)]
        self.assertEqual(filter_history(points, date(2016, 1, 1)), points)

    def test_percentile_labels_use_approved_four_bands(self):
        self.assertEqual(classify_percentile(19.99), "偏低")
        self.assertEqual(classify_percentile(20), "合理偏低")
        self.assertEqual(classify_percentile(49.99), "合理偏低")
        self.assertEqual(classify_percentile(50), "合理偏高")
        self.assertEqual(classify_percentile(79.99), "合理偏高")
        self.assertEqual(classify_percentile(80), "偏高")

    def test_invalid_record_returns_explicit_field_errors(self):
        record = {
            "code": "",
            "name": "测试",
            "pe_ttm": 301,
            "percentile": -1,
            "as_of": "2026/01/01",
            "freshness": "unknown",
            "history": [],
        }
        errors = validate_index_record(record)
        self.assertTrue(any("code" in item for item in errors))
        self.assertTrue(any("pe_ttm" in item for item in errors))
        self.assertTrue(any("percentile" in item for item in errors))
        self.assertTrue(any("as_of" in item for item in errors))
        self.assertTrue(any("freshness" in item for item in errors))

    def test_explicit_unavailable_record_allows_empty_valuation_fields(self):
        record = {
            "code": "931750",
            "name": "中证沪港深CXO",
            "pe_ttm": None,
            "percentile": None,
            "as_of": None,
            "freshness": "unavailable",
            "history": [],
        }
        self.assertEqual(validate_index_record(record), [])


if __name__ == "__main__":
    unittest.main()
