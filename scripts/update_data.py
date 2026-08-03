"""Build and atomically publish the pharmaceutical valuation snapshot."""

import argparse
import json
import os
import tempfile
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

from funddb_client import FundDBClient
from sw_client import SWClient
from valuation import calculate_percentile, classify_percentile, filter_history, validate_index_record


SOURCE = "FundDB（支付宝整体法PE-TTM口径）"
SW_SOURCE = "申万宏源研究（整体法PE，与FundDB逐日交叉核对）"
CATALOG = (
    {"category": "医药行业", "name": "中证医药", "code": "000933", "role": "primary"},
    {"category": "医药行业", "name": "中证全指医药", "code": "000991", "role": "reference"},
    {"category": "创新药", "name": "SHS创新药", "code": "931409", "role": "primary"},
    {"category": "创新药", "name": "中证创新药", "code": "931152", "role": "reference"},
    {"category": "CXO", "name": "中证沪港深CXO", "code": "931750", "role": "primary", "unavailable": True},
    {"category": "医疗器械", "name": "中证全指医疗器械", "code": "H30217", "role": "primary"},
    {"category": "医疗服务", "name": "申万医疗服务", "code": "801156", "role": "primary", "provider": "sw"},
    {"category": "医疗服务", "name": "中证医疗（参考）", "code": "399989", "role": "reference"},
    {"category": "生物疫苗", "name": "中证疫苗与生物技术", "code": "931992", "role": "primary", "unavailable": True},
    {"category": "生物疫苗", "name": "国证疫苗生物（参考）", "code": "980015", "role": "reference"},
    {"category": "中药", "name": "中证中药", "code": "930641", "role": "primary"},
    {"category": "医药商业", "name": "申万医药商业", "code": "801154", "role": "primary", "provider": "sw"},
)


def _unavailable_record(item, note):
    return {
        **{key: item[key] for key in ("category", "name", "code", "role")},
        "source_code": item["code"],
        "source": SOURCE,
        "pe_ttm": None,
        "percentile": None,
        "band": "数据暂缺",
        "as_of": None,
        "history_start": None,
        "observations": 0,
        "freshness": "unavailable",
        "note": note,
        "history": [],
    }


def _stale(previous, note):
    record = deepcopy(previous)
    record["freshness"] = "stale"
    record["note"] = note
    return record


def _publishable_previous(record):
    return (
        bool(record)
        and record.get("freshness") in {"current", "stale"}
        and not validate_index_record(record)
    )


def _cutoff(anchor):
    today = anchor.date() if isinstance(anchor, datetime) else anchor
    try:
        return today.replace(year=today.year - 10)
    except ValueError:
        return today.replace(year=today.year - 10, day=28)


def _sample_history(history, limit=600):
    if len(history) <= limit:
        return history
    step = (len(history) - 1) / (limit - 1)
    return [history[round(index * step)] for index in range(limit)]


def build_snapshot(client, previous, now=None, sw_client=None):
    now = now or datetime.now(timezone.utc)
    previous_by_code = {item["code"].upper(): item for item in (previous or {}).get("indices", [])}
    try:
        current_by_code = client.fetch_current_list()
    except Exception:
        current_by_code = {}

    records = []
    for item in CATALOG:
        code = item["code"].upper()
        old = previous_by_code.get(code)
        if item.get("unavailable"):
            records.append(_unavailable_record(item, "公开数据源暂无该指数同口径历史PE，未使用其他口径替代。"))
            continue
        if item.get("provider") == "sw":
            try:
                raw_history = sw_client.fetch_history(code, years=10)
                if not raw_history:
                    raise ValueError("empty SW history")
                market_date = date.fromisoformat(raw_history[-1][0])
                history = filter_history(raw_history, _cutoff(market_date))
                pe = round(float(history[-1][1]), 2)
                percentile = calculate_percentile([value for _, value in history], pe)
                chart_history = _sample_history(history)
                record = {
                    **{key: item[key] for key in ("category", "name", "code", "role")},
                    "source_code": f"{code}.SI",
                    "source": SW_SOURCE,
                    "pe_ttm": pe,
                    "percentile": percentile,
                    "band": classify_percentile(percentile),
                    "as_of": history[-1][0],
                    "history_start": history[0][0],
                    "observations": len(history),
                    "freshness": "current",
                    "note": "",
                    "history": [{"date": point_date, "pe": value} for point_date, value in chart_history],
                }
                errors = validate_index_record(record)
                if errors:
                    raise ValueError("; ".join(errors))
                records.append(record)
            except Exception:
                if _publishable_previous(old):
                    records.append(_stale(old, "本次更新失败，沿用上次成功数据。"))
                else:
                    records.append(_unavailable_record(item, "本次申万数据获取失败，且没有可用的历史快照。"))
            continue
        try:
            current = current_by_code[code]
            market_date = date.fromisoformat(current["as_of"])
            history = filter_history(client.fetch_history(current["source_code"], years=10), _cutoff(market_date))
            pe = round(float(current["pe_ttm"]), 2)
            percentile = calculate_percentile([value for _, value in history], pe)
            chart_history = _sample_history(history)
            record = {
                **{key: item[key] for key in ("category", "name", "code", "role")},
                "source_code": current["source_code"],
                "source": SOURCE,
                "pe_ttm": pe,
                "percentile": percentile,
                "band": classify_percentile(percentile),
                "as_of": current["as_of"],
                "history_start": history[0][0] if history else None,
                "observations": len(history),
                "freshness": "current",
                "note": "参考项不替代对应细分类目的精确指数。" if item["role"] == "reference" else "",
                "history": [{"date": point_date, "pe": value} for point_date, value in chart_history],
            }
            errors = validate_index_record(record)
            if errors:
                raise ValueError("; ".join(errors))
            records.append(record)
        except Exception:
            if _publishable_previous(old):
                records.append(_stale(old, "本次更新失败，沿用上次成功数据。"))
            else:
                records.append(_unavailable_record(item, "本次数据获取失败，且没有可用的历史快照。"))

    summary = {
        state: sum(record["freshness"] == state for record in records)
        for state in ("current", "stale", "unavailable")
    }
    return {
        "schema_version": 1,
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "methodology": {
            "pe": "整体法PE-TTM（与支付宝指数估值口径交叉核对）",
            "percentile": "最近十年日频有效PE中，小于或等于当前PE的样本占比；成立不足十年按成立以来。",
        },
        "summary": summary,
        "indices": records,
    }


def _validate_snapshot(snapshot):
    if snapshot.get("schema_version") != 1 or not isinstance(snapshot.get("indices"), list):
        raise ValueError("invalid snapshot schema")
    if not any(item.get("freshness") in {"current", "stale"} for item in snapshot["indices"]):
        raise ValueError("snapshot contains no publishable valuation")


def atomic_write_snapshot(path, snapshot):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _validate_snapshot(snapshot)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f"{path.name}.", suffix=".tmp", delete=False,
        ) as temp:
            temp_path = Path(temp.name)
            json.dump(snapshot, temp, ensure_ascii=False, indent=2)
            temp.write("\n")
            temp.flush()
            os.fsync(temp.fileno())
        with temp_path.open(encoding="utf-8") as saved:
            _validate_snapshot(json.load(saved))
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def _load_snapshot(*paths):
    for path in paths:
        if path and Path(path).exists():
            try:
                return json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/valuations.json")
    parser.add_argument("--fallback", default="data/valuations.last-good.json")
    args = parser.parse_args()
    previous = _load_snapshot(args.fallback, args.output)
    snapshot = build_snapshot(FundDBClient(), previous, sw_client=SWClient())
    atomic_write_snapshot(args.output, snapshot)
    atomic_write_snapshot(args.fallback, snapshot)
    counts = snapshot["summary"]
    print(f"current={counts['current']} stale={counts['stale']} unavailable={counts['unavailable']}")


if __name__ == "__main__":
    main()
