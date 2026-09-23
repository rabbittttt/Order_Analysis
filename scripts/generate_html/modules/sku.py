from __future__ import annotations

import logging
import re

from core.components import kpi, section, table
from core.excel import WorkbookStore, cell_number, clean_text
from core.models import Dashboard, SourceRef, Subject

LOGGER = logging.getLogger(__name__)


def _comparison(current, previous) -> dict:
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)):
        return {"status": "unavailable"}
    delta = current - previous
    return {
        "status": "available",
        "previous": previous,
        "delta": delta,
        "rate": delta / abs(previous) if previous else None,
        "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
    }


def find_header_row(sheet, required: tuple[str, ...], max_scan_rows: int = 15) -> int | None:
    normalized = {clean_text(label) for label in required}
    for row in range(1, min(sheet.max_row, max_scan_rows) + 1):
        labels = {clean_text(sheet.cell(row, col).value) for col in range(1, sheet.max_column + 1)}
        if normalized.issubset(labels):
            return row
    return None


def find_header(sheet, label: str, start: int = 1, header_row: int | None = None) -> int | None:
    row = header_row or find_header_row(sheet, (label,))
    if row is None:
        return None
    for col in range(start, sheet.max_column + 1):
        if clean_text(sheet.cell(row, col).value) == label:
            return col
    return None


def combo_heat_groups(sheet, periods: list[str], latest: str) -> list[dict]:
    """解析组合Sheet:行=TOP排名(值为累计占比),维度列=该排名的组合内容,周期列=各周期累计占比。"""
    header_row = find_header_row(sheet, ("累计锁单",))
    if header_row is None:
        LOGGER.warning("SKU组合表头识别失败: Sheet=%s 缺少‘累计锁单’，已跳过组合热力图", sheet.title)
        return []
    groups = []
    starts = [
        col for col in range(1, sheet.max_column + 1)
        if clean_text(sheet.cell(header_row, col).value) == "累计锁单"
    ]
    for start in starts:
        dimension_cols = []
        col = start + 1
        while col <= sheet.max_column:
            header = clean_text(sheet.cell(header_row, col).value)
            if header in periods or header in {"总计", ""}:
                break
            dimension_cols.append(col)
            col += 1
        period_cols = []
        for candidate in range(col, sheet.max_column + 1):
            header = clean_text(sheet.cell(header_row, candidate).value)
            if header in {"总计", ""}:
                break
            period_cols.append(candidate)
        if not period_cols:
            continue
        group_periods = [clean_text(sheet.cell(header_row, candidate).value) for candidate in period_cols]
        title = clean_text(sheet.cell(max(header_row - 1, 1), start).value).replace("配置组合_", "")
        rows = []
        for row in range(header_row + 1, sheet.max_row + 1):
            rank = clean_text(sheet.cell(row, start).value)
            if not rank:
                continue
            dims = [clean_text(sheet.cell(row, dim_col).value) for dim_col in dimension_cols]
            dims = [dim for dim in dims if dim]
            values = [cell_number(sheet.cell(row, candidate), rate=True) for candidate in period_cols]
            rows.append({"rank": rank, "label": " × ".join(dims) if dims else rank, "values": values})
        groups.append({"name": title, "periods": group_periods, "rows": rows})
    return groups


class SkuModule:
    id = "sku"
    label = "SKU收敛"

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        sku_found = store.find_subject_sheet("SKU收敛度", subject.name, suffix="_SKU")
        combo_found = store.find_subject_sheet("SKU收敛度", subject.name, suffix="_组合")
        if not sku_found or not combo_found:
            return None
        item, sku_sheet = sku_found
        _, combo_sheet = combo_found
        sku_source = SourceRef(item.path.name, sku_sheet.title, "SKU销量与累计占比")
        combo_source = SourceRef(item.path.name, combo_sheet.title, "配置组合热力图")

        header_row = find_header_row(sku_sheet, ("总计占比",))
        if header_row is None:
            LOGGER.warning("SKU表头识别失败: 主体=%s Sheet=%s 缺少‘总计占比’，已跳过该看板", subject.name, sku_sheet.title)
            return None
        total_col = find_header(sku_sheet, "总计占比", 6, header_row) or sku_sheet.max_column
        period_cols = [col for col in range(6, total_col) if clean_text(sku_sheet.cell(header_row, col).value)]
        periods = [clean_text(sku_sheet.cell(header_row, col).value) for col in period_cols] or ["最新周期"]
        sku_rows = []
        for row in range(header_row + 1, sku_sheet.max_row + 1):
            code = clean_text(sku_sheet.cell(row, 1).value)
            if not code:
                continue
            sku_rows.append({
                "code": code,
                "version": clean_text(sku_sheet.cell(row, 2).value),
                "exterior": clean_text(sku_sheet.cell(row, 3).value),
                "interior": clean_text(sku_sheet.cell(row, 4).value),
                "wheel": clean_text(sku_sheet.cell(row, 5).value),
                "values": [cell_number(sku_sheet.cell(row, col), rate=True) for col in period_cols],
            })

        cumulative_start = find_header(sku_sheet, "累计锁单", header_row=header_row)
        cumulative_rows = []
        if cumulative_start:
            cumulative_total = find_header(sku_sheet, "总计", cumulative_start + 1, header_row) or sku_sheet.max_column
            cumulative_period_cols = [
                col for col in range(cumulative_start + 1, cumulative_total)
                if clean_text(sku_sheet.cell(header_row, col).value)
            ]
            cumulative_periods = [clean_text(sku_sheet.cell(header_row, col).value) for col in cumulative_period_cols]
            if cumulative_periods:
                periods = cumulative_periods
            for row in range(header_row + 1, sku_sheet.max_row + 1):
                label = clean_text(sku_sheet.cell(row, cumulative_start).value)
                if label:
                    cumulative_rows.append({
                        "label": label.upper(),
                        "values": [cell_number(sku_sheet.cell(row, col), rate=True) for col in cumulative_period_cols],
                    })

        latest_index = max(len(periods) - 1, 0)
        latest = periods[latest_index]

        def period_metrics(index: int) -> list:
            top_map = {
                row["label"]: row["values"][index]
                for row in cumulative_rows if len(row["values"]) > index
            }
            coverage_80 = next(
                (row["label"] for row in cumulative_rows if len(row["values"]) > index and row["values"][index] >= .8),
                "-",
            )
            coverage_match = re.search(r"\d+", coverage_80)
            coverage_value = int(coverage_match.group()) if coverage_match else coverage_80
            active_sku = sum(
                1 for row in sku_rows
                if len(row["values"]) > index and row["values"][index] > 0
            )
            return [
                active_sku,
                top_map.get("TOP3", 0) * 100,
                top_map.get("TOP5", top_map.get("TOP3", 0)) * 100,
                coverage_value,
            ]

        latest_metrics = period_metrics(latest_index)
        previous_metrics = period_metrics(latest_index - 1) if latest_index > 0 else [None] * 4

        latest_sku_rows = sorted(
            sku_rows,
            key=lambda row: row["values"][latest_index] if len(row["values"]) > latest_index else 0,
            reverse=True,
        )
        ranking_rows = [
            [index, row["code"], " / ".join(value for value in (row["exterior"], row["interior"]) if value),
             row["values"][latest_index] if len(row["values"]) > latest_index else 0]
            for index, row in enumerate(latest_sku_rows, start=1)
        ]
        tail_rows = [
            {
                "label": period,
                "value": sum(1 for row in sku_rows if len(row["values"]) > index and 0 < row["values"][index] <= .05),
            }
            for index, period in enumerate(periods)
        ]
        heat_groups = combo_heat_groups(combo_sheet, periods, latest)

        kpis = [
            kpi("有效SKU", latest_metrics[0], "个", "当前周期", "blue"),
            kpi("TOP3累计", latest_metrics[1], "%", "锁单占比", "green"),
            kpi("TOP5累计", latest_metrics[2], "%", "锁单占比", "orange"),
            kpi("覆盖80%的SKU", latest_metrics[3], "个" if isinstance(latest_metrics[3], int) else "", "SKU数量", "purple"),
        ]
        for item, current, previous in zip(kpis, latest_metrics, previous_metrics):
            item["comparison"] = _comparison(current, previous)

        page = {
            "kpis": kpis,
            "sections": [
                section("sku_heatmap", "TOP1-TOP15 周度累计锁单占比", {"periods": periods, "rows": cumulative_rows}, "颜色越深，主销SKU集中度越高", source=sku_source),
                section("combo_matrix", "配置组合热力图", {"groups": heat_groups, "period": latest}, latest, source=combo_source),
                section("table", "主销SKU排行", table(["排名", "SKU", "配置", "占比"], ranking_rows, formats=["number", "text", "text", "percent"]), "当周锁单占比", "half", sku_source),
                section("tail_distribution", "长尾分布", tail_rows, "SKU数量（单周占比≤5%）", "half", sku_source),
            ],
        }
        views = {"week": {"periods": [latest], "default_period": latest, "pages": {latest: page}}}
        return Dashboard(self.id, subject.id, views, [sku_source, combo_source])
