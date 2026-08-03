"""Pure valuation calculations shared by the updater and its tests."""

import math
from datetime import date


def _valid_pe(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and 0 < value <= 300


def filter_history(points, cutoff_date):
    filtered = []
    for raw_date, raw_pe in points:
        try:
            point_date = date.fromisoformat(raw_date)
        except (TypeError, ValueError):
            continue
        if point_date >= cutoff_date and _valid_pe(raw_pe):
            filtered.append((raw_date, float(raw_pe)))
    return filtered


def calculate_percentile(history, current):
    values = [float(value) for value in history if _valid_pe(value)]
    if not values or not _valid_pe(current):
        raise ValueError("percentile requires a valid current PE and non-empty history")
    return round(sum(value <= current for value in values) * 100 / len(values), 2)


def classify_percentile(percentile):
    if not isinstance(percentile, (int, float)) or not math.isfinite(percentile):
        raise ValueError("percentile must be a finite number")
    if percentile < 20:
        return "偏低"
    if percentile < 50:
        return "合理偏低"
    if percentile < 80:
        return "合理偏高"
    return "偏高"


def validate_index_record(record):
    errors = []
    if not isinstance(record.get("code"), str) or not record.get("code"):
        errors.append("code must be a non-empty string")
    if not isinstance(record.get("name"), str) or not record.get("name"):
        errors.append("name must be a non-empty string")
    if record.get("freshness") == "unavailable":
        if record.get("pe_ttm") is not None or record.get("percentile") is not None:
            errors.append("unavailable records must not contain valuation values")
        if record.get("history") != []:
            errors.append("unavailable records must have empty history")
        return errors
    if not _valid_pe(record.get("pe_ttm")):
        errors.append("pe_ttm must be a finite number in (0, 300]")
    percentile = record.get("percentile")
    if not isinstance(percentile, (int, float)) or not math.isfinite(percentile) or not 0 <= percentile <= 100:
        errors.append("percentile must be a finite number in [0, 100]")
    try:
        date.fromisoformat(record.get("as_of", ""))
    except (TypeError, ValueError):
        errors.append("as_of must be an ISO date")
    if record.get("freshness") not in {"current", "stale"}:
        errors.append("freshness must be current or stale")
    history = record.get("history")
    if not isinstance(history, list) or not history:
        errors.append("history must be a non-empty list")
    return errors
