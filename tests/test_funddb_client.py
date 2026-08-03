import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from funddb_client import FundDBClient, signed_payload  # noqa: E402


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class FundDBClientTests(unittest.TestCase):
    def test_signature_matches_verified_server_contract(self):
        result = signed_payload({"category_id": ""}, now_ms=1_700_000_000_000)
        self.assertEqual(result["tirgkjfs"], "15")
        self.assertEqual(result["abiokytke"], "be")
        self.assertEqual(result["u54rg5d"], "50")
        self.assertEqual(result["quikgdky"], "9b")

    def test_server_errors_are_retried_three_times_with_backoff(self):
        session = FakeSession(
            [
                FakeResponse(500, {}),
                FakeResponse(503, {}),
                FakeResponse(200, {"data": {"items": []}}),
            ]
        )
        delays = []
        client = FundDBClient(session=session, sleeper=delays.append)

        self.assertEqual(client.fetch_current_list(), {})
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(delays, [1, 2])
        self.assertEqual(session.calls[0][1]["timeout"], (10, 30))

    def test_malformed_successful_json_is_not_retried(self):
        session = FakeSession([FakeResponse(200, ValueError("bad json"))])
        client = FundDBClient(session=session, sleeper=lambda _: None)

        with self.assertRaises(ValueError):
            client.fetch_current_list()
        self.assertEqual(len(session.calls), 1)

    def test_current_list_normalizes_live_right_list_fields(self):
        response = {
            "data": {
                "right_list": [
                    {
                        "gu_code": "931409.CSI",
                        "gu_name": "SHS创新药",
                        "gu_pe": "43.74",
                        "gu_date": "2026-07-31",
                    }
                ]
            }
        }
        client = FundDBClient(
            session=FakeSession([FakeResponse(200, response)]),
            sleeper=lambda _: None,
        )

        self.assertEqual(
            client.fetch_current_list()["931409"],
            {
                "source_code": "931409.CSI",
                "name": "SHS创新药",
                "pe_ttm": 43.74,
                "as_of": "2026-07-31",
            },
        )

    def test_history_selects_pe_series_and_uses_shanghai_dates(self):
        response = {
            "data": {
                "tubiao": {"series": [
                    {"name": "市净率", "data": [[1_704_038_400_000, 3.1]]},
                    {
                        "name": "市盈率",
                        "data": [
                            [1_704_038_400_000, 30.5],
                            [1_704_124_800_000, 31.2],
                        ],
                    },
                ]}
            }
        }
        client = FundDBClient(
            session=FakeSession([FakeResponse(200, response)]),
            sleeper=lambda _: None,
        )

        self.assertEqual(
            client.fetch_history("931409"),
            [("2024-01-01", 30.5), ("2024-01-02", 31.2)],
        )
        sent = client.session.calls[0][1]["data"]
        self.assertEqual(sent["gu_code"], "931409")
        self.assertEqual(sent["pe_category"], "pe")
        self.assertEqual(sent["year"], 10)


if __name__ == "__main__":
    unittest.main()
