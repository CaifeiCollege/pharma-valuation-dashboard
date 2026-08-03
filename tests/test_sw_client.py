import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sw_client import SWClient  # noqa: E402


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self.payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class SWClientTests(unittest.TestCase):
    def test_fetch_history_paginates_and_returns_sorted_pe_points(self):
        first = {
            "code": "200",
            "data": {
                "count": 3,
                "results": [
                    {"bargaindate": "2026-07-30T08:00:00+08:00", "pe": "17.80"},
                    {"bargaindate": "2026-07-29T08:00:00+08:00", "pe": "17.78"},
                ],
            },
        }
        second = {
            "code": "200",
            "data": {
                "count": 3,
                "results": [
                    {"bargaindate": "2026-07-28T08:00:00+08:00", "pe": "17.59"},
                ],
            },
        }
        session = FakeSession([FakeResponse(200, first), FakeResponse(200, second)])
        client = SWClient(session=session, sleeper=lambda _: None, page_size=2)

        self.assertEqual(
            client.fetch_history("801154", years=10),
            [("2026-07-28", 17.59), ("2026-07-29", 17.78), ("2026-07-30", 17.8)],
        )
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0][1]["params"]["index_type"], "二级行业")
        self.assertFalse(session.calls[0][1]["verify"])

    def test_server_errors_retry_three_times(self):
        success = {"code": "200", "data": {"count": 0, "results": []}}
        session = FakeSession([
            FakeResponse(500, {}),
            FakeResponse(503, {}),
            FakeResponse(200, success),
        ])
        delays = []
        client = SWClient(session=session, sleeper=delays.append)

        self.assertEqual(client.fetch_history("801156", years=10), [])
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(delays, [1, 2])


if __name__ == "__main__":
    unittest.main()
