from __future__ import annotations

import logging
import re
from datetime import date, datetime

from core.components import kpi, section
from core.excel import (
    WorkbookStore,
    cell_number,
    clean_text,
    compact_identifier,
    compact_text,
    display_period,
    parse_metric_sheet,
    safe_number,
    safe_rate,
)
from core.models import Dashboard, SourceRef, Subject


LOGGER = logging.getLogger(__name__)


def _header_key(value) -> str:
    return compact_identifier(value).replace("%", "").replace("％", "")


def _find_header(sheet, aliases: dict[str, set[str]], required: set[str], label: str) -> tuple[int, dict[str, int]] | None:
    normalized = {field: {_header_key(value) for value in values} for field, values in aliases.items()}
    best: tuple[int, int, dict[str, int]] | None = None
    for row in range(1, min(sheet.max_row, 12) + 1):
        columns: dict[str, int] = {}
        for column in range(1, sheet.max_column + 1):
            key = _header_key(sheet.cell(row, column).value)
            if not key:
                continue
            for field, keys in normalized.items():
                if key in keys:
                    columns.setdefault(field, column)
                    break
        candidate = (len(columns), -row, columns)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if not best or not required.issubset(best[2]):
        found = set(best[2]) if best else set()
        LOGGER.warning(
            "%s %s表头识别失败：缺少%s；不会按固定列号回退",
            sheet.title, label, "、".join(sorted(required - found)) or "必要字段",
        )
        return None
    return -best[1] + 1, best[2]


HOURLY_HEADERS = {
    "date": {"小订日期", "下单日期", "日期"},
    "hour": {"小订小时", "小时", "时段"},
    "orders": {"小订数", "小订数量"},
    "cancel": {"总退订数", "退订数", "总取消数"},
}
DAILY_HEADERS = {
    "date": {"取消日期", "退订日期", "日期"},
    "daily_small": {"当日小订退", "当日小订退订", "当日小订后退订"},
    "cumulative_small": {"累计小订退", "累计小订退订"},
    "daily_big": {"当日退订数", "当日大定退", "当日大定退订"},
    "conversion_rate": {"整体 - 小订转大定 %", "整体-小订转大定比例", "小订转大定比例", "小转大率"},
    "small_rate": {"整体 - 小订退 %", "整体-小订后退订%", "小订退订率"},
    "big_rate": {"整体 - 大定退 %", "整体-大定后退订%", "大定退订率"},
}
SELECT_HEADERS = {
    "orders": {"小订数", "小订数量"},
    "count": {"总退订数", "退订数", "总取消数"},
    "pre_share": {"小订后退订比例", "小订退订比例"},
    "post_share": {"大定后退订比例", "大定退订比例"},
    "share": {"总退订比例", "总退订率"},
}


def _period_key(value: str) -> str:
    """归一化日期键：2026/04/22 与 2026/4/22 视为同一周期。"""
    return re.sub(r"(?<=[/\-.])\s*0+(?=\d)", "", compact_text(value))


def _date_text(value, number_format: str = "") -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return display_period(value, number_format).replace("T00:00:00", "").replace(" 00:00:00", "")


def _metric(metrics: dict[str, float], preferred: str, fallback_index: int = 0) -> float:
    if preferred in metrics:
        return metrics[preferred]
    values = list(metrics.values())
    return values[fallback_index] if fallback_index < len(values) else 0.0


def parse_select_retreat(sheet) -> list[dict]:
    """解析选配退订 Sheet 的区块布局（地理区域/版本/电池包/外观/内饰/轮毂/选配项）。"""
    groups: list[dict] = []
    current: dict | None = None
    normalized_aliases = {field: {_header_key(value) for value in values} for field, values in SELECT_HEADERS.items()}
    for row in range(1, sheet.max_row + 1):
        values = [clean_text(sheet.cell(row, column).value) for column in range(1, sheet.max_column + 1)]
        nonempty = [value for value in values if value]
        if not nonempty:
            continue
        if len(nonempty) == 1 and nonempty[0].endswith("退订比例"):
            current = {"name": nonempty[0], "rows": [], "columns": None}
            groups.append(current)
            continue
        if current is None:
            continue
        header_columns: dict[str, int] = {}
        unmatched_columns = []
        for index, value in enumerate(values, start=1):
            key = _header_key(value)
            if not key:
                continue
            field = next((field for field, keys in normalized_aliases.items() if key in keys), None)
            if field:
                header_columns.setdefault(field, index)
            else:
                unmatched_columns.append(index)
        if {"orders", "count", "share"}.issubset(header_columns) and unmatched_columns:
            current["columns"] = {**header_columns, "label": unmatched_columns[0]}
            continue
        columns = current.get("columns")
        if not columns:
            continue
        label = clean_text(sheet.cell(row, columns["label"]).value)
        if not label:
            continue
        current["rows"].append({
            "label": label,
            "orders": safe_number(sheet.cell(row, columns["orders"]).value),
            "count": safe_number(sheet.cell(row, columns["count"]).value),
            "pre_share": cell_number(sheet.cell(row, columns["pre_share"]), rate=True) if columns.get("pre_share") else 0.0,
            "post_share": cell_number(sheet.cell(row, columns["post_share"]), rate=True) if columns.get("post_share") else 0.0,
            "share": cell_number(sheet.cell(row, columns["share"]), rate=True),
        })
    for group in groups:
        if group.get("columns") is None:
            LOGGER.warning("%s 的“%s”区块未识别到选配退订表头，已跳过", sheet.title, group["name"])
    return [{"name": group["name"], "rows": group["rows"]} for group in groups if group["rows"]]


def _parse_hourly_retreat(sheet) -> list[dict]:
    resolved = _find_header(sheet, HOURLY_HEADERS, {"date", "hour", "orders", "cancel"}, "小订分时退订")
    if resolved is None:
        return []
    start_row, columns = resolved
    rows = []
    for row in range(start_row, sheet.max_row + 1):
        date_cell = sheet.cell(row, columns["date"])
        period = _date_text(date_cell.value, date_cell.number_format)
        if not period:
            continue
        rows.append({
            "period": period,
            "hour": safe_number(sheet.cell(row, columns["hour"]).value),
            "count": safe_number(sheet.cell(row, columns["orders"]).value),
            "cancel": safe_number(sheet.cell(row, columns["cancel"]).value),
        })
    return rows


def _parse_daily_retreat(sheet) -> list[dict]:
    required = {"date", "daily_small", "cumulative_small", "daily_big", "conversion_rate", "small_rate", "big_rate"}
    resolved = _find_header(sheet, DAILY_HEADERS, required, "日度退订")
    if resolved is None:
        return []
    start_row, columns = resolved
    rows = []
    for row in range(start_row, sheet.max_row + 1):
        date_cell = sheet.cell(row, columns["date"])
        period = _date_text(date_cell.value, date_cell.number_format)
        if not period:
            continue
        rows.append({
            "period": period,
            "daily": safe_number(sheet.cell(row, columns["daily_small"]).value),
            "big_daily": safe_number(sheet.cell(row, columns["daily_big"]).value),
            "cumulative": safe_number(sheet.cell(row, columns["cumulative_small"]).value),
            "convert_rate": cell_number(sheet.cell(row, columns["conversion_rate"]), rate=True),
            "small_rate": cell_number(sheet.cell(row, columns["small_rate"]), rate=True),
            "big_rate": cell_number(sheet.cell(row, columns["big_rate"]), rate=True),
        })
    return rows


class CancellationModule:
    id = "cancellation"
    label = "小订节奏"

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        small_mix = store.find_subject_sheet("小订选配比例", subject.name, "day")
        day = store.find_subject_sheet("小订退订", subject.name, suffix="_日度退订")
        hourly = store.find_subject_sheet("小订退订", subject.name, suffix="_小订分时退订")
        select = store.find_subject_sheet("小订退订", subject.name, suffix="_选配退订")
        if not small_mix or not day:
            return None

        small_item, small_sheet = small_mix
        cancel_item, day_sheet = day
        small_source = SourceRef(small_item.path.name, small_sheet.title, "小订期间订单与留存")
        day_source = SourceRef(cancel_item.path.name, day_sheet.title, "小订期间日度退订")
        hourly_source = SourceRef(hourly[0].path.name, hourly[1].title, "小订分时节奏") if hourly else None
        select_source = SourceRef(select[0].path.name, select[1].title, "选配维度退订") if select else None

        # 小订分时退订 Sheet：按小订日期聚合小订数与退订数（下单与退订同口径，用于留存计算）。
        # 注意：日度退订 Sheet 是“当日退的订单”（不一定是当日下单），不能用于留存反推。
        hourly_by_period: dict[str, dict] = {}
        hourly_rows = _parse_hourly_retreat(hourly[1]) if hourly else []
        if hourly:
            for row in hourly_rows:
                key = _period_key(row["period"])
                entry = hourly_by_period.setdefault(key, {"orders": 0.0, "cancel": 0.0})
                entry["orders"] += row["count"]
                entry["cancel"] += row["cancel"]

        parsed = parse_metric_sheet(small_sheet)
        # 当分时退订表与小订节奏表的日期范围不重叠时，仍使用同日期的日度小订退订数，
        # 避免“小订期订单节奏”整段退订显示为 0。若分时数据存在，则优先使用分时口径。
        daily_rows = _parse_daily_retreat(day_sheet)
        daily_cancel_by_period = {
            _period_key(row["period"]): row["daily"]
            for row in daily_rows
        }
        periods = [period for period in parsed if not any(marker in period for marker in ("近", "汇总", "累计", "总计"))]
        if not periods:
            periods = list(parsed)
        rhythm_rows = []
        for period in periods:
            metrics = parsed[period]["metrics"]
            period_key = _period_key(period)
            has_hourly = period_key in hourly_by_period
            totals = hourly_by_period.get(period_key, {})
            orders = totals.get("orders") or metrics.get("小订") or _metric(metrics, "净小订", 0)
            cancel = totals.get("cancel", 0.0) if has_hourly else daily_cancel_by_period.get(period_key, 0.0)
            retained = max(orders - cancel, 0)
            rhythm_rows.append({
                "period": period,
                "orders": orders,
                "retained": retained,
                "cancel": cancel,
                "retention_rate": safe_rate(retained, orders),
                "cancel_rate": safe_rate(cancel, orders),
            })

        start_label = ""
        if hourly_rows:
            start_label = f"{hourly_rows[0]['period']} {int(hourly_rows[0]['hour']):02d}:00"

        # 日度退订趋势：当日小订退/大定退(柱) + 累计小订退率/大定退率/小转大率(折线)

        total_orders = sum(row["orders"] for row in rhythm_rows)
        total_retained = sum(row["retained"] for row in rhythm_rows)
        total_cancel = sum(row["cancel"] for row in rhythm_rows)
        page = {
            "kpis": [
                kpi("小订期累计", total_orders, "单", f"{len(rhythm_rows)}个自然日", "blue"),
                kpi("累计留存小订", total_retained, "单", "小订期间", "green"),
                kpi("累计退订", total_cancel, "单", "小订期间", "coral"),
                kpi("阶段留存率", safe_rate(total_retained, total_orders) * 100, "%", "留存小订 / 小订", "purple"),
            ],
            "sections": [
                section(
                    "small_order_rhythm",
                    "小订期订单节奏",
                    rhythm_rows,
                    "小订 / 留存 / 退订 / 留存率",
                    source=small_source,
                ),
            ],
        }
        if hourly_rows:
            hourly_meta = f"小订开启 {start_label} · 识别高峰时段与退订波动" if start_label else "识别高峰时段与退订波动"
            page["sections"].append(section(
                "hourly",
                "分时小订与退订节奏",
                hourly_rows,
                hourly_meta,
                source=hourly_source,
            ))
        if daily_rows:
            page["sections"].append(section(
                "daily_cancel",
                "日度退订趋势",
                daily_rows,
                "当日小订退/大定退 · 累计小订退率/大定退率/小转大率",
                source=day_source,
            ))
        if select:
            select_groups = parse_select_retreat(select[1])
            if select_groups:
                ranking = []
                for group in select_groups:
                    name = group["name"][:-4] if group["name"].endswith("退订比例") else group["name"]
                    for row in group["rows"]:
                        ranking.append({"label": f"{name} · {row['label']}", "share": row["share"], "count": row["count"]})
                ranking.sort(key=lambda item: item["share"], reverse=True)
                page["sections"].append(section(
                    "bars",
                    "选配退订率排行",
                    {"color": "coral", "rows": ranking[:15]},
                    "跨维度 TOP15 · 总退订率",
                    source=select_source,
                ))

        # 统计截止日 = 已按表头识别的最后一个日度退订日期
        stat_end = daily_rows[-1]["period"] if daily_rows else ""
        period_label = stat_end or "—"

        views = {"day": {"periods": [period_label], "default_period": period_label, "pages": {period_label: page}}}
        sources = [small_source, day_source, *([hourly_source] if hourly_source else []), *([select_source] if select_source else [])]
        return Dashboard(self.id, subject.id, views, sources)
