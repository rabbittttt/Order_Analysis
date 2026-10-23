from __future__ import annotations

import logging
import math
import re

from core.components import kpi, section
from core.excel import WorkbookStore, _daily_period, _period_sort, clean_text, compact_diagnostic_ranges, compact_text, display_period
from core.models import Dashboard, SourceRef, Subject


LOGGER = logging.getLogger(__name__)

# 品牌渠道阵地总数：可直接修改；车型默认继承父品牌，不跨品牌借用分母。
# 渠道名称原样对应 Excel 的“分类”列，不做别名归类。
# 显式设为 0 的渠道在看板中隐藏；未配置不等于 0，仍保留原始分类。
CHANNEL_STORE_COUNTS = {
    "问界": {"问界用户中心": 374, "鸿蒙智行用户中心": 28, "华为旗舰店": 11,
           "华为授权体验店": 131, "华为智能生活馆": 425},
    "智界": {"智界用户中心": 48, "鸿蒙智行用户中心": 334, "华为旗舰店": 11,
           "华为授权体验店": 129, "华为智能生活馆": 388},
    "尊界": {"鸿蒙智行用户中心": 157, "华为旗舰店": 7, "华为授权体验店": 3,
           "华为智能生活馆": 35, "尊界用户中心": 9, "智界用户中心": 1, "问界用户中心": 2},
    "尚界": {"尚界用户中心": 221, "鸿蒙智行用户中心": 259, "华为旗舰店": 13,
           "华为授权体验店": 153, "华为智能生活馆": 450},
    "享界": {"享界用户中心": 14, "鸿蒙智行用户中心": 344, "华为旗舰店": 11,
           "华为授权体验店": 100, "华为智能生活馆": 387},
}
# 可选主体覆盖，例如 {"问界": {"华为授权体验店": 90},
# "问界 M9 2026款": {"华为授权体验店": 75}}。
# 优先级：车型自身 > 父品牌覆盖 > 上面的品牌配置。
# 集团各渠道按品牌生效配置相加（含品牌覆盖，共用门店也累加）；
# 不叠加车型覆盖，也不单独设置集团覆盖。
CHANNEL_STORE_COUNTS_BY_SUBJECT: dict[str, dict[str, int | float | None]] = {}

_FIELDS = {("门店类型", "数量"): "count", ("门店类型", "占比"): "share",
           ("门店类型", "贡献门店数"): "active_count",
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


def _period_columns(sheet, grain):
    period_label = _daily_period if grain == "day" else display_period
    columns = {}
    for column in range(4, sheet.max_column + 1):
        cell = sheet.cell(1, column)
        period = period_label(cell.value, cell.number_format)
        if period and not _AGGREGATE.search(period):
            columns[column] = period
    return columns


def _channel_rows(sheet):
    metric = stat = ""
    for row in range(2, sheet.max_row + 1):
        metric = clean_text(sheet.cell(row, 1).value) or metric
        stat = clean_text(sheet.cell(row, 2).value) or stat
        channel = clean_text(sheet.cell(row, 3).value)
        field = _FIELDS.get((metric, stat))
        if not field or not channel or channel in {"数量", "总计", "合计", "汇总"}:
            continue
        yield row, channel, field, (2 if stat == "贡献门店数" else 1)


def _parse_channels(sheet, grain):
    columns = _period_columns(sheet, grain)
    periods = sorted(set(columns.values()), key=_period_sort)
    parsed = {period: {} for period in periods}
    source_rows = list(_channel_rows(sheet))
    # Only the original 门店类型 block defines categories and their order.
    # Legacy contributing-store rows can fill matching names, never add aliases.
    channels = list(dict.fromkeys(channel for _, channel, field, priority in source_rows
                                  if field != "active_count" or priority == 2))
    priorities = {}
    # Merged sheets manufacture blank cells where a physical row/period never
    # existed. Only an actual new-format cell (including a blank) overrides the
    # legacy value; a newer export must not erase old-format historical periods.
    matches = getattr(sheet, "_source_matches", None)
    new_cells = None
    if matches:
        new_cells = set()
        for _, original in matches:
            source_periods = _period_columns(original, grain).values()
            for _, channel, field, priority in _channel_rows(original):
                if field == "active_count" and priority == 2:
                    new_cells.update((period, channel) for period in source_periods)
    for row, channel, field, priority in source_rows:
        if channel not in channels:
            continue
        for column, period in columns.items():
            key = period, channel, field
            if field == "active_count" and priority == 2 and new_cells is not None and (period, channel) not in new_cells:
                continue
            if priority < priorities.get(key, 0):
                continue
            priorities[key] = priority
            cell = sheet.cell(row, column)
            parsed[period].setdefault(channel, {})[field] = _number(
                cell.value, rate=field == "share", number_format=cell.number_format)
    return channels, parsed


def _store_counts(subject):
    if subject.type == "group":
        counts = {}
        for brand in CHANNEL_STORE_COUNTS:
            for name, value in _store_counts(Subject(brand, brand, "brand")).items():
                number = _number(value)
                previous = counts.get(name, 0)
                counts[name] = previous + number if previous is not None and number is not None else None
        return counts
    brand = subject.parent if subject.type == "generation" else subject.name if subject.type == "brand" else None
    counts = dict(next((value for key, value in CHANNEL_STORE_COUNTS.items()
                        if brand and compact_text(key) == compact_text(brand)), {}))
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


def _totals(rows, configured):
    count = _complete_sum(rows, "count")
    active = _complete_sum(rows, "active_count")
    denominators = [_number(value) for value in configured.values()]
    total = sum(denominators) if denominators and all(value is not None for value in denominators) else None
    # Include every configured channel in the denominator, even if its source
    # row is absent. An unconfigured channel with activity leaves coverage unknown.
    if any(row["store_count"] is None and (row["count"] != 0 or row["active_count"] != 0) for row in rows):
        total = None
    inconsistent = any(row["active_count"] is not None and row["store_count"] is not None
                       and row["active_count"] > row["store_count"] for row in rows)
    return {"count": count, "active_count": active, "store_count": total,
            "active_rate": active / total if active is not None and total and not inconsistent else None,
            "productivity": count / total if count is not None and total else None}


class ChannelAnalysisModule:
    id = "channel_analysis"
    label = "渠道分析"

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        views, sources = {}, []
        inconsistencies = {}
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
            source = SourceRef(item.path.name, sheet.title, "门店类型（数量 / 占比 / 贡献门店数，兼容原贡献订单门店数）")
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
                        issue = inconsistencies.setdefault(channel, {"periods": {}, "sources": [], "examples": [], "count": 0})
                        issue["count"] += 1
                        issue["periods"].setdefault(grain, []).append(period)
                        if source not in issue["sources"]:
                            issue["sources"].append(source)
                        if len(issue["examples"]) < 3:
                            issue["examples"].append(
                                f"{period}: 留存大定={count}, 出单门店={active}, 总门店={total}")
                    row = {"channel": channel, "count": count, "share": share, "store_count": total,
                           "active_count": active,
                           "active_rate": active / denominator if active is not None and denominator and not inconsistent else None,
                           "productivity": count / denominator if count is not None and denominator else None}
                    prior = previous.get(channel, {})
                    for field in ("count", "share", "active_rate", "productivity"):
                        row[f"previous_{field}"] = prior.get(field)
                        row[f"{field}_change"] = _delta(row[field], prior.get(field))
                    rows.append(row)
                history.append({"period": period, "rows": rows, "totals": _totals(rows, configured)})
                previous = {row["channel"]: row for row in rows}

            pages = {}
            for entry in history:
                period, rows = entry["period"], entry["rows"]
                totals = entry["totals"]
                count, active, rate, productivity = (totals[key] for key in ("count", "active_count", "active_rate", "productivity"))
                pages[period] = {
                    "kpis": [
                        kpi("渠道留存大定", count, "单", "门店类型原始数量合计", "blue"),
                        kpi("出单门店数", active, "家", "当期贡献订单门店", "green"),
                        kpi("出单门店比例", rate * 100 if rate is not None else None, "%", "出单门店数 / 配置总门店数", "purple"),
                        kpi("单店产能", productivity, "单/店", "留存大定 / 配置总门店数", "orange"),
                    ],
                    "sections": [section("channel_panel", title,
                                         {"metric": metric, "period": period, "rows": rows, "history": history, "totals": totals},
                                         meta, source=source)
                                 for metric, title, meta in (
                                     ("sales", "各渠道留存大定及占比", "直接读取门店类型原始数量和占比"),
                                     ("stores", "贡献订单门店", "出单门店数 / 该渠道总门店数"),
                                     ("capacity", "单店产能", "留存大定 / 该渠道总门店数"))],
                }
            views[grain] = {"periods": periods, "default_period": periods[-1], "pages": pages}
        grain_labels = {"day": "日", "week": "周", "month": "月"}
        for channel, issue in inconsistencies.items():
            periods = "；".join(f"{grain_labels[grain]}="
                               f"{compact_diagnostic_ranges(values)}（{len(values)}项）"
                               for grain, values in issue["periods"].items())
            locations = "；".join(f"{source.file} / Sheet={source.sheet}" for source in issue["sources"])
            LOGGER.warning("[渠道门店数据不一致] 主体=%s | 渠道=%s | 共%d项 | 全部周期=%s | 来源=%s | 示例=%s | 处理=相关出单比例留空",
                           subject.name, channel, issue["count"], periods, locations, "；".join(issue["examples"]))
        return Dashboard(self.id, subject.id, views, sources) if views else None
