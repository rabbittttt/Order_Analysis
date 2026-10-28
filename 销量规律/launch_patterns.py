"""Launch-batch pacing ratios for retained deposits and delivery locks.

The module intentionally works on the already validated daily panel.  It does
not synthesize missing launch days and keeps each model, launch anchor, metric,
and source separate so that a source change cannot create a false 14/21-day
series.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from numbers import Real
from typing import Any, Iterable, Mapping


TARGET_METRICS = ("留存大定", "交车锁单")
_WINDOWS = (
    ("首销第2周/第1周", 8, 14, 1, 7),
    ("首销第3周/第2周", 15, 21, 8, 14),
)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _valid_anchor(row: Mapping[str, Any]) -> tuple[date, date, int] | None:
    anchor = _as_date(row.get("cycle"))
    day = _as_date(row.get("date"))
    life_value = row.get("life")
    if anchor is None or day is None or life_value is None:
        return None
    if isinstance(life_value, str):
        text = life_value.strip().upper()
        if text.startswith("D"):
            text = text[1:]
        if not text.isdigit():
            return None
        life = int(text)
    else:
        if isinstance(life_value, bool):
            return None
        if isinstance(life_value, Real) and not float(life_value).is_integer():
            return None
        try:
            life = int(life_value)
        except (TypeError, ValueError):
            return None
    if life <= 0 or day != anchor + timedelta(days=life - 1):
        return None
    return anchor, day, life


def _source_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (str(row.get("model", "")), str(row.get("metric", "")),
            str(row.get("stage", "")), str(row.get("cycle", "")),
            str(row.get("source", "")))


def _window_result(
    rows: list[Mapping[str, Any]],
    anchor: date,
    pattern: str,
    current_start_day: int,
    current_end_day: int,
    previous_start_day: int,
    previous_end_day: int,
) -> dict[str, Any] | None:
    by_day = {_as_date(row.get("date")): row for row in rows}
    current_start = anchor + timedelta(days=current_start_day - 1)
    current_end = anchor + timedelta(days=current_end_day - 1)
    previous_start = anchor + timedelta(days=previous_start_day - 1)
    previous_end = anchor + timedelta(days=previous_end_day - 1)
    current_rows = [by_day[d] for d in _days(current_start, current_end) if d in by_day]
    if not current_rows:
        # The comparison was not touched by actual observations.  Do not
        # create a future or synthetic third-week row.
        return None
    previous_rows = [by_day[d] for d in _days(previous_start, previous_end) if d in by_day]
    current_values = [float(row["value"]) for row in current_rows]
    previous_values = [float(row["value"]) for row in previous_rows]
    current = sum(current_values)
    previous = sum(previous_values) if previous_rows else None
    current_negative = any(value < 0 for value in current_values)
    previous_negative = any(value < 0 for value in previous_values)

    ratio = None
    if current_negative:
        status = "本期含负值"
    elif previous_negative:
        status = "前期含负值"
    elif len(current_rows) != 7:
        status = "本期缺失或不完整"
    elif len(previous_rows) != 7:
        status = "前期缺失或不完整"
    elif previous == 0:
        status = "前期为零"
    elif previous < 0:
        status = "前期为负"
    else:
        ratio = current / previous
        status = "有效"

    first = rows[0]
    return {
        "model": str(first.get("model", "")),
        "metric": first.get("metric"),
        "stage": first.get("stage"),
        "cycle": anchor.isoformat(),
        "source": first.get("source", ""),
        "brand": first.get("brand", "未提供"),
        "segment": first.get("segment", "未提供"),
        "energy": first.get("energy", "未提供"),
        "pattern": pattern,
        "start": current_start,
        "end": current_end,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "current": current,
        "previous": previous,
        "ratio": ratio,
        "status": status,
        "current_observed": len(current_rows),
        "previous_observed": len(previous_rows),
    }


def _days(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def build_launch_pacing(panel: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Return actual second/third launch-week comparisons.

    Rows must belong to the ``首销`` stage and have a valid date anchor and
    lifecycle number.  A missing or invalid day remains missing; values are
    never forward-filled, distributed, or copied from another source.
    """
    groups: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    seen: set[tuple[tuple[str, str, str, str, str], date]] = set()
    for row in panel or ():
        if not isinstance(row, Mapping) or row.get("metric") not in TARGET_METRICS:
            continue
        if row.get("stage") != "首销":
            continue
        valid = _valid_anchor(row)
        value = _number(row.get("value"))
        if valid is None or value is None:
            continue
        anchor, day, _ = valid
        key = _source_key(dict(row, cycle=anchor.isoformat()))
        duplicate_key = (key, day)
        if duplicate_key in seen:
            raise ValueError("首销节奏同一日重复，拒绝覆盖：" + repr(duplicate_key))
        seen.add(duplicate_key)
        groups[key].append(dict(row, value=value, date=day, cycle=anchor.isoformat()))

    output: list[dict[str, Any]] = []
    for rows in groups.values():
        rows.sort(key=lambda row: _as_date(row.get("date")) or date.max)
        anchor = _as_date(rows[0].get("cycle"))
        if anchor is None:
            continue
        for pattern, current_start, current_end, previous_start, previous_end in _WINDOWS:
            result = _window_result(rows, anchor, pattern, current_start, current_end,
                                    previous_start, previous_end)
            if result is not None:
                output.append(result)
    pattern_order = {name: index for index, (name, *_rest) in enumerate(_WINDOWS)}
    output.sort(key=lambda row: (row["model"], row["metric"], row["cycle"],
                                 pattern_order.get(row["pattern"], 99), row["source"]))
    return output


# Keep a descriptive alias for callers that use the analysis verb.
analyze_launch_pacing = build_launch_pacing


__all__ = ["TARGET_METRICS", "build_launch_pacing", "analyze_launch_pacing"]
