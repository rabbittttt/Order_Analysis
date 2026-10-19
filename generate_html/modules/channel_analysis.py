from __future__ import annotations

import logging
import math
import re

from core.components import kpi, section
from core.excel import WorkbookStore, _daily_period, _period_sort, clean_text, compact_text, display_period
from core.models import Dashboard, SourceRef, Subject


LOGGER = logging.getLogger(__name__)

# 示例门店总数：请在这里修改为实际渠道阵地数量；用于出单比例和单店产能。
# 配置不负责识别/归类渠道，渠道名称直接读取 Excel 的“分类”列。
CHANNEL_STORE_COUNTS = {
    "华为授权体验店": 120,
    "华为智能生活馆": 60,
    "华为旗舰店": 12,
    "鸿蒙智行用户中心": 80,
    "问界用户中心": 100,
    "智界用户中心": 45,
    "享界用户中心": 35,
    "尊界用户中心": 20,
    "尚界用户中心": 55,
    "未知门店类型": 15,
}
# 可选主体覆盖，例如 {"问界": {"华为授权体验店": 90},
# "问界 M9 2026款": {"华为授权体验店": 75}}。
# 优先级：车型自身 > 父品牌 > 上面的全局配置；未填写的渠道沿用上一级。
CHANNEL_STORE_COUNTS_BY_SUBJECT: dict[str, dict[str, int | float | None]] = {}

_FIELDS = {("门店类型", "数量"): "count", ("门店类型", "占比"): "share",
           ("贡献订单门店数", "数量"): "active_count"}
_AGGREGATE = re.compile(r"总计|合计|汇总|累计|近\s*\d+\s*(?:天|日|周|月)")


def _number(value, *, rate=False, number_format="") -> float | None:
    """Unknown cells stay unknown; genuine numeric zero is never discarded."""
    if value is None or isinstance(value, bool):
        return None
    percent = False
    if isinstance(value, str):
        text = clean_text(value).replace(",", "").replace("，", "")
        percent = text.endswith(("%", "％"))
        if percent:
            if not rate:
                return None
            text = text[:-1].strip()
        if not re.fullmatch(r"\+?(?:\d+(?:\.\d*)?|\.\d+)", text):
            return None
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    if rate:
        if percent or ("%" not in number_format and "％" not in number_format and number > 1.5):
            number /= 100
        if number > 1:
            return None
    return number


def _parse_channels(sheet, grain):
    period_label = _daily_period if grain == "day" else display_period
    columns = {}
    for column in range(4, sheet.max_column + 1):
        cell = sheet.cell(1, column)
        period = period_label(cell.value, cell.number_format)
        if period and not _AGGREGATE.search(period):
            columns[column] = period
    periods = sorted(set(columns.values()), key=_period_sort)
    parsed = {period: {} for period in periods}
    channels = []
    metric = stat = ""
    for row in range(2, sheet.max_row + 1):
        metric = clean_text(sheet.cell(row, 1).value) or metric
        stat = clean_text(sheet.cell(row, 2).value) or stat
        channel = clean_text(sheet.cell(row, 3).value)
        field = _FIELDS.get((metric, stat))
        if not field or not channel or channel in {"数量", "总计", "合计", "汇总"}:
            continue
        if channel not in channels:
            channels.append(channel)
        for column, period in columns.items():
            cell = sheet.cell(row, column)
            parsed[period].setdefault(channel, {})[field] = _number(
                cell.value, rate=field == "share", number_format=cell.number_format)
    return channels, parsed


def _store_counts(subject):
    counts = dict(CHANNEL_STORE_COUNTS)
    subjects = ([subject.parent] if subject.type == "generation" and subject.parent else []) + [subject.name]
    for name in subjects:
        override = next((value for key, value in CHANNEL_STORE_COUNTS_BY_SUBJECT.items()
                         if compact_text(key) == compact_text(name)), {})
        counts.update(override)
    return counts


def _delta(current, previous):
    return current - previous if current is not None and previous is not None else None


def _complete_sum(rows, field):
    values = [row[field] for row in rows]
    return sum(values) if values and all(value is not None for value in values) else None


class ChannelAnalysisModule:
    id = "channel_analysis"
    label = "渠道分析"

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        views, sources = {}, []
        configured = _store_counts(subject)
        for grain in ("day", "week", "month"):
            found = store.find_subject_sheet("大定选配比例", subject.name, grain)
            if not found:
                continue
            item, sheet = found
            channels, parsed = _parse_channels(sheet, grain)
            if not channels or not any(value is not None for period in parsed.values()
                                       for row in period.values() for value in row.values()):
                continue
            source = SourceRef(item.path.name, sheet.title, "门店类型 / 贡献订单门店数")
            sources.append(source)
            periods = list(parsed)
            history, previous = [], {}
            for period, values in parsed.items():
                rows = []
                for channel in channels:
                    original = values.get(channel, {})
                    count, share, active = (original.get(field) for field in ("count", "share", "active_count"))
                    total = _number(configured.get(channel))
                    denominator = total if total is not None and total > 0 else None
                    inconsistent = active is not None and total is not None and active > total
                    if inconsistent:
                        LOGGER.warning("[渠道门店数据不一致] %s | %s | %s | 留存大定=%s | 出单门店=%s | 总门店=%s | 出单比例留空",
                                       subject.name, period, channel, count, active, total)
                    row = {"channel": channel, "count": count, "share": share, "store_count": total,
                           "active_count": active,
                           "active_rate": active / denominator if active is not None and denominator and not inconsistent else None,
                           "productivity": count / denominator if count is not None and denominator else None}
                    prior = previous.get(channel, {})
                    for field in ("count", "share", "active_rate", "productivity"):
                        row[f"previous_{field}"] = prior.get(field)
                        row[f"{field}_change"] = _delta(row[field], prior.get(field))
                    rows.append(row)
                history.append({"period": period, "rows": rows})
                previous = {row["channel"]: row for row in rows}

            pages = {}
            for entry in history:
                period, rows = entry["period"], entry["rows"]
                count = _complete_sum(rows, "count")
                active = _complete_sum(rows, "active_count")
                total = _complete_sum(rows, "store_count")
                rate = active / total if (active is not None and total and
                                         all(row["active_rate"] is not None for row in rows)) else None
                productivity = count / total if (count is not None and total and
                                                 all(row["productivity"] is not None for row in rows)) else None
                pages[period] = {
                    "kpis": [
                        kpi("渠道留存大定", count, "单", "门店类型原始数量合计", "blue"),
                        kpi("出单门店数", active, "家", "当期贡献订单门店", "green"),
                        kpi("出单门店比例", rate * 100 if rate is not None else None, "%", "出单门店数 / 配置总门店数", "purple"),
                        kpi("单店产能", productivity, "单/店", "留存大定 / 配置总门店数", "orange"),
                    ],
                    "sections": [section("channel_panel", title,
                                         {"metric": metric, "period": period, "rows": rows, "history": history},
                                         meta, source=source)
                                 for metric, title, meta in (
                                     ("sales", "各渠道留存大定及占比", "直接读取门店类型原始数量和占比"),
                                     ("stores", "贡献订单门店", "出单门店数 / 该渠道总门店数"),
                                     ("capacity", "单店产能", "留存大定 / 该渠道总门店数"))],
                }
            views[grain] = {"periods": periods, "default_period": periods[-1], "pages": pages}
        return Dashboard(self.id, subject.id, views, sources) if views else None
