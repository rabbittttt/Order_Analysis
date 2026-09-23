from __future__ import annotations

import logging

from core.components import kpi, section, table
from core.excel import WorkbookStore, clean_text, compact_identifier, safe_number, safe_rate
from core.models import Dashboard, SourceRef, Subject


LOGGER = logging.getLogger(__name__)
STAGES = ("大定", "留存大定", "销售锁单", "交车锁单", "已发运", "已到店", "已交付")
PERIOD_HEADERS = {"周", "月", "周期", "统计周期"}
QUANTITY_HEADERS = {"数量", "订单量", "订单数", "单量"}
ORDER_TO_LOCK_HEADERS = {"大定到交车锁单（天）", "大定到交车锁单天数", "大定至交车锁单（天）", "大定至交车锁单天数"}
LOCK_TO_DELIVERY_HEADERS = {"交车锁单到交付（天）", "交车锁单到交付天数", "交车锁单至交付（天）", "交车锁单至交付天数"}


def _header_key(value) -> str:
    return compact_identifier(value).replace("%", "").replace("％", "")


def _conversion_columns(sheet) -> tuple[int, int, dict[str, int], int | None, int | None] | None:
    """Resolve the two-row conversion header without relying on physical column positions."""
    stage_keys = {_header_key(stage): stage for stage in STAGES}
    period_keys = {_header_key(value) for value in PERIOD_HEADERS}
    quantity_keys = {_header_key(value) for value in QUANTITY_HEADERS}
    order_to_lock_keys = {_header_key(value) for value in ORDER_TO_LOCK_HEADERS}
    lock_to_delivery_keys = {_header_key(value) for value in LOCK_TO_DELIVERY_HEADERS}
    best = None
    for header_row in range(1, min(sheet.max_row, 10) + 1):
        subheader_row = header_row + 1
        current_group = ""
        period_column = None
        stage_columns: dict[str, int] = {}
        order_to_lock_column = None
        lock_to_delivery_column = None
        for column in range(1, sheet.max_column + 1):
            top = clean_text(sheet.cell(header_row, column).value)
            if top:
                current_group = top
            group_key = _header_key(current_group)
            sub = clean_text(sheet.cell(subheader_row, column).value) if subheader_row <= sheet.max_row else ""
            sub_key = _header_key(sub)
            if _header_key(top) in period_keys:
                period_column = column
            stage = stage_keys.get(group_key)
            if stage and (not sub_key or sub_key in quantity_keys):
                stage_columns.setdefault(stage, column)
            if sub_key in order_to_lock_keys or _header_key(top) in order_to_lock_keys:
                order_to_lock_column = column
            if sub_key in lock_to_delivery_keys or _header_key(top) in lock_to_delivery_keys:
                lock_to_delivery_column = column
        score = len(stage_columns) + int(period_column is not None)
        candidate = (score, -header_row, header_row, period_column, stage_columns, order_to_lock_column, lock_to_delivery_column)
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if not best:
        return None
    _, _, header_row, period_column, stage_columns, order_to_lock_column, lock_to_delivery_column = best
    missing = [stage for stage in STAGES if stage not in stage_columns]
    if period_column is None or missing:
        LOGGER.warning(
            "%s 表头识别失败：周期列=%s，缺少阶段=%s；不会按固定列号回退",
            sheet.title, period_column or "未找到", "、".join(missing) or "无",
        )
        return None
    if order_to_lock_column is None or lock_to_delivery_column is None:
        LOGGER.warning(
            "%s 转化时长表头不完整：大定到交车锁单=%s，交车锁单到交付=%s；缺失项按空值展示",
            sheet.title, order_to_lock_column or "未找到", lock_to_delivery_column or "未找到",
        )
    return header_row + 2, period_column, stage_columns, order_to_lock_column, lock_to_delivery_column


class ConversionModule:
    id = "conversion"
    label = "订单7级转化"

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        views = {}
        sources: list[SourceRef] = []
        for grain in ("week", "month"):
            found = store.find_subject_sheet("订单7级转化", subject.name, grain)
            if not found:
                continue
            item, sheet = found
            source = SourceRef(item.path.name, sheet.title, "订单批次转化")
            resolved_columns = _conversion_columns(sheet)
            if resolved_columns is None:
                continue
            data_start_row, period_column, stage_columns, order_to_lock_column, lock_to_delivery_column = resolved_columns
            cohorts = []
            for row in range(data_start_row, sheet.max_row + 1):
                period = clean_text(sheet.cell(row, period_column).value)
                if not period:
                    continue
                values = {label: safe_number(sheet.cell(row, stage_columns[label]).value) for label in STAGES}
                order = values["大定"]
                stages = []
                previous = order
                for label in STAGES:
                    value = values[label]
                    stages.append({
                        "label": label, "value": value, "total_rate": safe_rate(value, order),
                        "stage_rate": safe_rate(value, previous), "loss": max(previous - value, 0),
                    })
                    previous = value
                cohorts.append({
                    "period": period, "stages": stages,
                    "order_to_lock_days": safe_number(sheet.cell(row, order_to_lock_column).value) if order_to_lock_column else None,
                    "lock_to_delivery_days": safe_number(sheet.cell(row, lock_to_delivery_column).value) if lock_to_delivery_column else None,
                })
            if not cohorts:
                continue
            periods = [cohort["period"] for cohort in cohorts]
            pages = {}
            for cohort in cohorts:
                delivered = cohort["stages"][-1]["value"]
                order = cohort["stages"][0]["value"]
                loss_stages = [stage for stage in cohort["stages"][1:] if stage["loss"] > 0]
                largest_loss = max(loss_stages, key=lambda stage: stage["loss"], default={"label": "-", "loss": 0})
                loss_bars = [
                    {"label": stage["label"], "share": safe_rate(stage["loss"], order), "count": stage["loss"]}
                    for stage in loss_stages
                ]
                pages[cohort["period"]] = {
                    "kpis": [
                        kpi("总转化率", safe_rate(delivered, order) * 100, "%", "大定至已交付", "blue"),
                        kpi("本批次大定", order, "单", cohort["period"], "green"),
                        kpi("当前已交付", delivered, "单", "同一批订单", "orange"),
                        kpi("最大阶段流失", largest_loss["loss"], "单", largest_loss["label"], "orange"),
                    ],
                    "sections": [
                        section("funnel", "7级转化漏斗", cohort["stages"], "数量 / 总占比 / 阶段转化 / 流失", source=source),
                        section("cohort_matrix", "批次转化矩阵", cohorts, "阶段转化率与转化时长", source=source),
                        section("bars", "阶段流失占比", {"color": "orange", "rows": loss_bars}, "相对大定订单", source=source),
                    ],
                }
            views[grain] = {"periods": periods, "default_period": periods[-1], "pages": pages}
            sources.append(source)
        return Dashboard(self.id, subject.id, views, sources) if views else None
