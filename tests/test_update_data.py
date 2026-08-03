import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from update_data import atomic_write_snapshot, build_snapshot  # noqa: E402


NOW = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def old_record(code="000933", pe=31.97):
    return {
        "category": "医药行业",
        "name": "中证医药",
        "code": code,
        "source_code": f"{code}.CSI",
        "source": "FundDB（支付宝整体法PE-TTM口径）",
        "role": "primary",
        "pe_ttm": pe,
        "percentile": 45.98,
        "band": "偏低",
        "as_of": "2026-07-28",
        "history_start": "2016-08-03",
        "observations": 2,
        "freshness": "current",
        "note": "",
        "history": [
            {"date": "2016-08-03", "pe": 20.0},
            {"date": "2026-07-28", "pe": pe},
        ],
    }


class FakeClient:
    def __init__(self, current=None, histories=None, current_error=None):
        self.current = current or {}
        self.histories = histories or {}
        self.current_error = current_error

    def fetch_current_list(self):
        if self.current_error:
            raise self.current_error
        return self.current

    def fetch_history(self, source_code, years=10):
        value = self.histories[source_code]
        if isinstance(value, Exception):
            raise value
        return value


class FakeSWClient:
    def __init__(self, histories):
        self.histories = histories

    def fetch_history(self, code, years=10):
        value = self.histories[code]
        if isinstance(value, Exception):
            raise value
        return value


class SnapshotUpdaterTests(unittest.TestCase):
    def test_failed_index_uses_previous_record_as_stale(self):
        previous_record = old_record()
        client = FakeClient(
            current={
                "000933": {
                    "source_code": "000933.SH",
                    "name": "中证医药",
                    "pe_ttm": 32.5,
                    "as_of": "2026-07-31",
                }
            },
            histories={"000933.SH": RuntimeError("temporary outage")},
        )

        snapshot = build_snapshot(
            client,
            {"schema_version": 1, "indices": [previous_record]},
            NOW,
        )
        record = next(item for item in snapshot["indices"] if item["code"] == "000933")
        self.assertEqual(record["pe_ttm"], 31.97)
        self.assertEqual(record["freshness"], "stale")
        self.assertIn("沿用", record["note"])

    def test_total_source_failure_with_valid_previous_snapshot_does_not_raise(self):
        previous_record = old_record()
        snapshot = build_snapshot(
            FakeClient(current_error=RuntimeError("offline")),
            {"schema_version": 1, "indices": [previous_record]},
            NOW,
        )
        record = next(item for item in snapshot["indices"] if item["code"] == "000933")
        self.assertEqual(record["freshness"], "stale")
        self.assertGreaterEqual(snapshot["summary"]["stale"], 1)
        self.assertGreaterEqual(snapshot["summary"]["unavailable"], 4)

    def test_invalid_new_pe_cannot_replace_valid_previous_record(self):
        previous_record = old_record()
        client = FakeClient(
            current={
                "000933": {
                    "source_code": "000933.SH",
                    "name": "中证医药",
                    "pe_ttm": 999,
                    "as_of": "2026-07-31",
                }
            },
            histories={"000933.SH": [("2026-07-31", 999)]},
        )
        snapshot = build_snapshot(client, {"schema_version": 1, "indices": [previous_record]}, NOW)
        record = next(item for item in snapshot["indices"] if item["code"] == "000933")
        self.assertEqual(record["pe_ttm"], 31.97)
        self.assertEqual(record["freshness"], "stale")

    def test_interrupted_replace_keeps_original_output_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "valuations.json"
            original = b'{"schema_version": 1, "sentinel": true}'
            output.write_bytes(original)
            snapshot = {
                "schema_version": 1,
                "generated_at": "2026-08-03T10:00:00Z",
                "indices": [old_record()],
            }

            with patch("update_data.os.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    atomic_write_snapshot(output, snapshot)

            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])

    def test_published_chart_history_is_downsampled_without_changing_observation_count(self):
        start = date(2023, 1, 1)
        history = [
            ((start + timedelta(days=index)).isoformat(), 20 + index % 31)
            for index in range(1000)
        ]
        client = FakeClient(
            current={
                "000933": {
                    "source_code": "000933.SH",
                    "name": "中证医药",
                    "pe_ttm": 32,
                    "as_of": history[-1][0],
                }
            },
            histories={"000933.SH": history},
        )
        snapshot = build_snapshot(client, None, NOW)
        record = next(item for item in snapshot["indices"] if item["code"] == "000933")

        self.assertEqual(record["observations"], 1000)
        self.assertLessEqual(len(record["history"]), 600)
        self.assertEqual(record["history"][0]["date"], history[0][0])
        self.assertEqual(record["history"][-1]["date"], history[-1][0])

    def test_ten_year_cutoff_is_anchored_to_market_date_not_job_run_date(self):
        history = [("2016-08-01", 20), ("2026-07-31", 32)]
        client = FakeClient(
            current={
                "000933": {
                    "source_code": "000933.SH",
                    "name": "中证医药",
                    "pe_ttm": 32,
                    "as_of": "2026-07-31",
                }
            },
            histories={"000933.SH": history},
        )
        snapshot = build_snapshot(client, None, NOW)
        record = next(item for item in snapshot["indices"] if item["code"] == "000933")

        self.assertEqual(record["observations"], 2)
        self.assertEqual(record["history_start"], "2016-08-01")

    def test_sw_exact_industries_use_same_method_history(self):
        sw_client = FakeSWClient({
            "801154": [("2026-07-29", 17.78), ("2026-07-30", 17.80)],
            "801156": [("2026-07-29", 28.10), ("2026-07-30", 28.16)],
        })
        snapshot = build_snapshot(FakeClient(current_error=RuntimeError("offline")), None, NOW, sw_client)

        commerce = next(item for item in snapshot["indices"] if item["code"] == "801154")
        services = next(item for item in snapshot["indices"] if item["code"] == "801156")
        self.assertEqual(commerce["pe_ttm"], 17.8)
        self.assertEqual(services["pe_ttm"], 28.16)
        self.assertEqual(commerce["freshness"], "current")
        self.assertIn("申万宏源研究", commerce["source"])

    def test_failed_sw_fetch_does_not_turn_unavailable_placeholder_into_stale_value(self):
        placeholder = {
            "category": "医药商业",
            "name": "申万医药商业",
            "code": "801154",
            "source_code": "801154",
            "source": "旧来源",
            "role": "primary",
            "pe_ttm": None,
            "percentile": None,
            "band": "数据暂缺",
            "as_of": None,
            "history_start": None,
            "observations": 0,
            "freshness": "unavailable",
            "note": "旧占位",
            "history": [],
        }
        sw_client = FakeSWClient({
            "801154": RuntimeError("offline"),
            "801156": RuntimeError("offline"),
        })
        snapshot = build_snapshot(
            FakeClient(current_error=RuntimeError("offline")),
            {"schema_version": 1, "indices": [placeholder]},
            NOW,
            sw_client,
        )
        commerce = next(item for item in snapshot["indices"] if item["code"] == "801154")

        self.assertEqual(commerce["freshness"], "unavailable")
        self.assertIsNone(commerce["pe_ttm"])


if __name__ == "__main__":
    unittest.main()
