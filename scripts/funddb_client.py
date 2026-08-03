"""Small signed client for FundDB's public valuation endpoints."""

import hashlib
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


HOST = "https://api.jiucaishuo.com"
SECRET = "EWf45rlv#kfsr@k#gfksgkr"
SIGNATURE_FIELDS = (
    "tirgkjfs", "abiokytke", "u54rg5d", "kf54ge7", "tiklsktr4",
    "lksytkjh", "sbnoywr", "bgd7h8tyu54", "y654b5fs3tr", "bioduytlw",
    "bd4uy742", "h67456y", "bvytikwqjk", "ngd4uy551", "bgiuytkw",
    "nd354uy4752", "ghtoiutkmlg", "bd24y6421f", "tbvdiuytk",
    "ibvytiqjek", "jnhf8u5231", "fjlkatj", "hy5641d321t", "iogojti",
    "ngd4yut78", "nkjhrew", "yt447e13f", "n3bf4uj7y7", "nbf4uj7y432",
    "yi854tew", "h13ey474", "quikgdky",
)


def signed_payload(payload, now_ms=None):
    data = dict(payload)
    data.update({
        "type": "pc",
        "version": "2.2.7",
        "authtoken": "",
        "act_time": int(time.time() * 1000) if now_ms is None else now_ms,
    })
    raw = "".join(
        str(data[key])
        for key in sorted(data)
        if data[key] is not None
        and not isinstance(data[key], (dict, list))
        and (data[key] != "" or data[key] == 0)
    )
    digest = hashlib.md5((raw + SECRET).encode()).hexdigest()
    pieces = {
        "c": digest[29:31], "d": digest[2:4], "f": digest[5:6],
        "h": digest[26:27], "m": digest[6:8], "v": digest[1:2],
        "y": digest[0:2], "k": digest[6:8], "w": digest[8:9],
        "x": digest[30:31], "j": digest[11:14], "P": digest[11:12],
        "z": digest[2:5], "q": digest[9:11], "E": digest[23:25],
        "H": digest[31:32], "O": digest[25:27], "A": digest[9:11],
        "C": digest[27:29], "T": digest[17:19], "I": digest[26:27],
        "U": digest[12:14], "S": digest[25:26], "R": digest[16:19],
        "F": digest[17:21], "B": digest[18:19], "K": digest[21:23],
        "D": digest[14:16], "$": digest[29:32], "N": digest[21:23],
        "V": digest[24:26], "L": digest[16:17],
    }
    order = ("y", "N", "d", "H", "v", "F", "E", "k", "P", "f", "I", "R",
             "m", "T", "A", "x", "j", "V", "L", "D", "q", "z", "O", "S",
             "U", "h", "w", "B", "K", "c", "$", "C")
    data.update(dict(zip(SIGNATURE_FIELDS, (pieces[key] for key in order))))
    return data


class FundDBClient:
    def __init__(self, session=None, sleeper=time.sleep):
        self.session = session or requests.Session()
        self.sleeper = sleeper

    def _post(self, path, payload):
        for attempt in range(3):
            try:
                response = self.session.post(
                    HOST + path,
                    data=signed_payload(payload),
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Origin": "https://funddb.cn",
                        "Referer": "https://funddb.cn/",
                    },
                    timeout=(10, 30),
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
            return response.json()
        raise RuntimeError("unreachable")

    def fetch_current_list(self):
        payload = self._post("/v2/guzhi/showcategory", {"category_id": ""})
        data = payload.get("data", {})
        items = data.get("right_list", data.get("items", [])) if isinstance(data, dict) else data
        result = {}
        for item in items or []:
            source_code = str(item.get("gu_code") or item.get("code") or item.get("index_code") or "")
            code = source_code.split(".", 1)[0].upper()
            if code:
                result[code] = {
                    "source_code": source_code,
                    "name": item.get("gu_name") or item.get("name") or "",
                    "pe_ttm": float(item.get("gu_pe") or item.get("pe_ttm")),
                    "as_of": item.get("gu_date") or item.get("as_of"),
                }
        return result

    def fetch_history(self, code, years=10):
        payload = self._post(
            "/v2/guzhi/newtubiaolinedata",
            {"gu_code": code, "pe_category": "pe", "year": years, "ver": "new"},
        )
        data = payload.get("data", {})
        chart = data.get("tubiao", data) if isinstance(data, dict) else {}
        series = chart.get("series", chart.get("list", [])) if isinstance(chart, dict) else []
        pe_series = next((item for item in series if item.get("name") == "市盈率"), None)
        if not pe_series:
            raise ValueError(f"PE-TTM history missing for {code}")
        shanghai = ZoneInfo("Asia/Shanghai")
        points = []
        for timestamp_ms, value in pe_series.get("data", []):
            point_date = datetime.fromtimestamp(timestamp_ms / 1000, shanghai).date().isoformat()
            points.append((point_date, float(value)))
        return points
