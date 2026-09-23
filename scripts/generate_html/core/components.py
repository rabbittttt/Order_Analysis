from __future__ import annotations

from typing import Any, Iterable


def kpi(label: str, value: Any, unit: str = "", note: str = "", color: str = "blue") -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, "note": note, "color": color}


def section(
    kind: str,
    title: str,
    data: Any,
    meta: str = "",
    width: str = "full",
    source: Any | None = None,
) -> dict[str, Any]:
    result = {"kind": kind, "title": title, "meta": meta, "width": width, "data": data}
    if source is not None:
        result["source"] = source.to_dict() if hasattr(source, "to_dict") else source
    return result


def table(columns: Iterable[str], rows: Iterable[Iterable[Any]], **extra: Any) -> dict[str, Any]:
    result = {"columns": list(columns), "rows": [list(row) for row in rows]}
    result.update(extra)
    return result


def bars(rows: Iterable[tuple[str, float, int | float | None]], color: str = "blue") -> dict[str, Any]:
    return {
        "color": color,
        "rows": [{"label": label, "value": value, "count": count} for label, value, count in rows],
    }


def add_kpi_comparisons(dashboards: dict[str, dict[str, Any]]) -> None:
    """Annotate KPI cards with the same metric's previous-period movement."""
    aggregate_markers = ("近", "汇总", "累计", "总计")
    for dashboard in dashboards.values():
        for view in dashboard.get("views", {}).values():
            periods = view.get("periods", [])
            pages = view.get("pages", {})
            for index, period in enumerate(periods):
                page = pages.get(period)
                if not page:
                    continue
                previous_page = pages.get(periods[index - 1]) if index and not any(marker in str(period) for marker in aggregate_markers) else None
                previous_kpis = {item.get("label"): item for item in (previous_page or {}).get("kpis", [])}
                for item in page.get("kpis", []):
                    if "comparison" in item:
                        continue
                    previous = previous_kpis.get(item.get("label"))
                    current_value = item.get("value")
                    previous_value = previous.get("value") if previous else None
                    if not isinstance(current_value, (int, float)) or not isinstance(previous_value, (int, float)):
                        item["comparison"] = {"status": "unavailable"}
                        continue
                    delta = current_value - previous_value
                    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
                    item["comparison"] = {
                        "status": "available",
                        "previous": previous_value,
                        "delta": delta,
                        "rate": delta / abs(previous_value) if previous_value else None,
                        "direction": direction,
                    }
