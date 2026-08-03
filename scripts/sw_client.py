"""Client for Shenwan Hongyuan's public industry-index valuation history."""

import math
import time
from datetime import date

import requests
import urllib3


URL = "https://www.swsresearch.com/institute-sw/api/index_analysis/index_analysis_report/"
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class SWClient:
    def __init__(self, session=None, sleeper=time.sleep, page_size=1000):
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.page_size = page_size

    def _get(self, params):
        for attempt in range(3):
            try:
                response = self.session.get(
                    URL,
                    params=params,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=(10, 30),
                    verify=False,
                )
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                self.sleeper(attempt + 1)
                continue
            if response.status_code >= 500:
                if attempt == 2:
                    response.raise_for_status()
                self.sleeper(attempt + 1)
                continue
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("code")) != "200":
                raise ValueError("SW valuation API returned an unsuccessful response")
            return payload.get("data") or {}
        raise RuntimeError("unreachable")

    def fetch_history(self, code, years=10):
        today = date.today()
        try:
            start = today.replace(year=today.year - years)
        except ValueError:
            start = today.replace(year=today.year - years, day=28)
        base = {
            "page_size": self.page_size,
            "index_type": "二级行业",
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
            "type": "DAY",
            "swindexcode": code,
        }
        rows = []
        page = 1
        while True:
            data = self._get({**base, "page": page})
            rows.extend(data.get("results") or [])
            if page * self.page_size >= int(data.get("count") or 0):
                break
            page += 1
        points = []
        for row in rows:
            try:
                value = float(row.get("pe"))
                point_date = date.fromisoformat(str(row.get("bargaindate"))[:10]).isoformat()
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and 0 < value <= 300:
                points.append((point_date, value))
        return sorted(dict(points).items())
