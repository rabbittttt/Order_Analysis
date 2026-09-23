from __future__ import annotations

import logging
import re
from collections import defaultdict
from functools import lru_cache

from core.components import kpi, section, table
from core.excel import WorkbookStore, cell_number, clean_text, compact_identifier, is_aggregate_generation, safe_number, safe_rate, sheet_subject
from core.models import Dashboard, SourceRef, Subject


AMOUNT_BANDS = ("免费", "0-5000", "5000-10000", "10000-15000", "15000-以上")
AGGREGATE_PERIODS = {"汇总", "合计", "总计"}
# 各代际金额段分档不同（5000元档 / 10000元档），品牌页按此顺序统一展示
BAND_ORDER = ("免费", "0-5000", "5000-10000", "10000-15000", "15000-以上", "0-10000", "10000-20000", "20000-30000", "30000-以上")
LOGGER = logging.getLogger(__name__)
PENETRATION_ALIASES = ("选配渗透率排名", "选配渗透率偏好排名", "选配渗透率")
PAID_ALIASES = ("付费选配占比", "付费选配比例", "付费选配占比排名", "付费选配偏好排名")


def _summary_column(sheet) -> int:
    """Locate the total column by its header instead of trusting max_column."""
    for row in range(1, min(sheet.max_row, 5) + 1):
        for col in range(1, sheet.max_column + 1):
            if compact_identifier(sheet.cell(row, col).value) in {"总计", "合计"}:
                return col
    return sheet.max_column


def _parse_rank_item(value) -> dict | None:
    """Parse cells such as '电动遮阳帘 77.5%\n(3000)' while keeping plain labels valid."""
    text = clean_text(value)
    if not text:
        return None
    amount_match = re.search(r"[（(]\s*([\d,，]+(?:\.\d+)?)\s*[)）]\s*$", text)
    rate_match = re.search(r"(-?\d+(?:\.\d+)?)\s*[%％]", text)
    label_end = min(
        [match.start() for match in (rate_match, amount_match) if match] or [len(text)]
    )
    label = text[:label_end].strip(" -—:：") or text
    item = {"label": label}
    if rate_match:
        item["rate"] = safe_number(rate_match.group(1)) / 100
    if amount_match:
        item["amount"] = safe_number(amount_match.group(1).replace("，", ","))
    return item


@lru_cache(maxsize=256)
def _normalize_band(value: str) -> str:
    raw = compact_identifier(value).replace("元", "")
    raw = raw.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    aliases = {compact_identifier(band): band for band in AMOUNT_BANDS}
    aliases.update({"0": "免费"})
    if raw in aliases:
        return aliases[raw]
    if "免费" in raw:
        return "免费"
    text = raw.replace("至", "-").replace("到", "-").replace("~", "-").replace("～", "-")
    match = re.search(r"(\d+)\s*[-—–](\d+)", text)
    if match:
        return f"{int(match.group(1))}-{int(match.group(2))}"
    match = re.search(r"(\d+)\s*(?:以下|以内)", text)
    if match:
        return f"0-{int(match.group(1))}"
    match = re.search(r"(\d+)\s*以上", text)
    if match:
        return f"{int(match.group(1))}-以上"
    return value


@lru_cache(maxsize=256)
def _is_amount_band(value: str) -> bool:
    normalized = _normalize_band(value)
    return normalized == "免费" or bool(re.fullmatch(r"\d+-(?:\d+|以上)", normalized))


def _option_layout(sheet) -> tuple[int, int, int]:
    """动态识别周期行、金额段行和订单量行。

    模板允许在顶部增删说明行，但金额段标题和订单数据的语义必须保留。
    """
    cached = getattr(sheet, "_order_analysis_option_layout", None)
    if cached is not None:
        return cached

    scan_rows = range(1, min(sheet.max_row, 15) + 1)
    scored = []
    for row in scan_rows:
        score = sum(
            1 for col in range(3, sheet.max_column + 1)
            if _is_amount_band(clean_text(sheet.cell(row, col).value))
        )
        if score:
            scored.append((score, row))
    if not scored:
        raise ValueError("未识别到金额段表头（例如‘免费’、‘0-5000’、‘5000-以上’）")
    band_row = max(scored)[1]
    period_row = band_row - 1
    band_columns = [
        col for col in range(3, sheet.max_column + 1)
        if _is_amount_band(clean_text(sheet.cell(band_row, col).value))
    ]
    order_row = 0
    for row in range(band_row + 1, min(sheet.max_row, band_row + 6) + 1):
        label = compact_identifier(f"{sheet.cell(row, 1).value or ''}{sheet.cell(row, 2).value or ''}")
        values = [sheet.cell(row, col).value for col in band_columns]
        numeric = [float(value) for value in values if isinstance(value, (int, float))]
        if numeric and (re.search(r"订单|数量|总计|合计", label) or any(abs(value) > 1 for value in numeric)):
            order_row = row
            break
    if not order_row:
        raise ValueError("已识别金额段表头，但其后5行内未识别到订单量行")
    layout = (period_row, band_row, order_row)
    # 生成期间工作簿只读；缓存在 Worksheet 实例上，随工作簿关闭一起释放。
    setattr(sheet, "_order_analysis_option_layout", layout)
    return layout


def _period_groups(sheet) -> tuple[list[str], dict[str, list[tuple[int, str]]]]:
    """Read merged month headers and their amount-band columns without fixed widths."""
    period_row, band_row, _ = _option_layout(sheet)
    periods: list[str] = []
    groups: dict[str, list[tuple[int, str]]] = defaultdict(list)
    current_period = ""
    for col in range(3, sheet.max_column + 1):
        header = clean_text(sheet.cell(period_row, col).value)
        if header:
            current_period = header
            if header not in AGGREGATE_PERIODS and header not in periods:
                periods.append(header)
        band = _normalize_band(clean_text(sheet.cell(band_row, col).value))
        if current_period and current_period not in AGGREGATE_PERIODS and band and band not in AGGREGATE_PERIODS:
            groups[current_period].append((col, band))
    return periods, groups


def _amount_rows(sheet) -> tuple[list[list], list[float], list[float]]:
    rows_by_version: dict[str, dict[str, float]] = defaultdict(dict)
    summary_col = sheet.max_column
    for row in range(1, sheet.max_row + 1):
        version = clean_text(sheet.cell(row, 1).value)
        metric = clean_text(sheet.cell(row, 2).value)
        if version and metric in {"选配金额", "实际金额"}:
            rows_by_version[version][metric] = safe_number(sheet.cell(row, summary_col).value)
    rows, option_values, actual_values = [], [], []
    for version, values in rows_by_version.items():
        option_amount = values.get("选配金额", 0)
        actual_amount = values.get("实际金额", 0)
        rows.append([version, option_amount, actual_amount, safe_rate(option_amount - actual_amount, option_amount)])
        option_values.append(option_amount)
        actual_values.append(actual_amount)
    return rows, option_values, actual_values


def _rights(sheet) -> tuple[float, str]:
    label = clean_text(sheet.cell(1, 1).value)
    value = clean_text(sheet.cell(1, 2).value)
    rights_amount = safe_number(value if label == "权益金额" else f"{label} {value}")
    rights_text = clean_text(sheet.cell(2, 2).value) if clean_text(sheet.cell(2, 1).value) == "权益内容" else ""
    return rights_amount, rights_text


def _total_rows(sheet) -> tuple[float, float]:
    """合计口径：末尾“选配金额”行与“实际金额”行的总计列值（倒数第二行/最后一行）。"""
    option_total = actual_total = 0.0
    for row in range(sheet.max_row, max(1, sheet.max_row - 15), -1):
        metric = clean_text(sheet.cell(row, 2).value)
        value = safe_number(sheet.cell(row, sheet.max_column).value)
        if metric == "选配金额" and not option_total:
            option_total = value
        elif metric == "实际金额" and not actual_total:
            actual_total = value
        if option_total and actual_total:
            break
    return option_total, actual_total


def _totals_by_period(sheet, periods: list[str]) -> dict[str, tuple[float, float]]:
    """Read each period's option/actual totals from its real column span."""
    result: dict[str, tuple[float, float]] = {period: (0.0, 0.0) for period in periods}
    option_row = actual_row = None
    for row in range(sheet.max_row, max(1, sheet.max_row - 20), -1):
        label = clean_text(sheet.cell(row, 1).value)
        metric = clean_text(sheet.cell(row, 2).value)
        if label == "合计" and metric == "选配金额总计":
            option_row = row
        elif label == "合计" and metric == "实际金额总计":
            actual_row = row
        if option_row and actual_row:
            break
    if option_row is None or actual_row is None:
        for row in range(sheet.max_row, max(1, sheet.max_row - 20), -1):
            metric = clean_text(sheet.cell(row, 2).value)
            if metric == "选配金额总计" and option_row is None:
                option_row = row
            elif metric == "实际金额总计" and actual_row is None:
                actual_row = row
    if option_row is not None and actual_row is not None:
        for period, start, end in _period_spans(sheet, periods):
            result[period] = (
                _period_amount_value(sheet, option_row, start, end),
                _period_amount_value(sheet, actual_row, start, end),
            )
    return result


def _period_spans(sheet, periods: list[str]) -> list[tuple[str, int, int]]:
    """Locate real month column ranges instead of assuming every block is six columns."""
    period_row, _, _ = _option_layout(sheet)
    starts: list[tuple[str, int]] = []
    for col in range(3, sheet.max_column + 1):
        header = clean_text(sheet.cell(period_row, col).value)
        if header in periods:
            starts.append((header, col))
    spans: list[tuple[str, int, int]] = []
    for index, (period, start) in enumerate(starts):
        next_start = starts[index + 1][1] if index + 1 < len(starts) else sheet.max_column + 1
        end = next_start - 1
        for col in range(start + 1, end + 1):
            if clean_text(sheet.cell(period_row, col).value) in AGGREGATE_PERIODS:
                end = col - 1
                break
        spans.append((period, start, end))
    return spans


def _period_amount_value(sheet, row: int, start: int, end: int) -> float:
    """Prefer a labelled total cell, then the first populated numeric cell in the block."""
    _, band_row, _ = _option_layout(sheet)
    total_columns = [
        col for col in range(start, end + 1)
        if clean_text(sheet.cell(band_row, col).value) in AGGREGATE_PERIODS
    ]
    ordered = total_columns + [col for col in range(start, end + 1) if col not in total_columns]
    fallback = 0.0
    for col in ordered:
        raw = sheet.cell(row, col).value
        if raw in (None, ""):
            continue
        value = safe_number(raw)
        if value:
            return value
        fallback = value
    return fallback


def _version_rows_by_period(sheet, periods: list[str]) -> dict[str, list[list]]:
    """版本选配金额与实际金额:每个版本(含合计)在选中周期下的金额与权益抵扣率。"""
    option_map: dict[str, int] = {}
    actual_map: dict[str, int] = {}
    current_version = ""
    _, _, order_row = _option_layout(sheet)
    for row in range(order_row + 1, sheet.max_row + 1):
        version = clean_text(sheet.cell(row, 1).value)
        metric = clean_text(sheet.cell(row, 2).value)
        if version:
            current_version = version
        if metric == "选配金额":
            option_map[current_version] = row
        elif metric == "实际金额":
            actual_map[current_version] = row
    versions = [version for version in option_map if version and version in actual_map]
    result: dict[str, list[list]] = {period: [] for period in periods}
    for period, start, end in _period_spans(sheet, periods):
        for version in versions:
            option = _period_amount_value(sheet, option_map[version], start, end)
            actual = _period_amount_value(sheet, actual_map[version], start, end)
            result[period].append([version, option, actual, safe_rate(option - actual, option)])
    return result


class OptionFeeModule:
    id = "option_fee"
    label = "选配金"

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        if subject.type == "brand":
            return self._build_brand(store, subject)
        if subject.type == "generation":
            return self._build_generation(store, subject)
        return None

    def _build_brand(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        penetration = store.find_subject_sheet("选配金统计", subject.name, suffix=PENETRATION_ALIASES)
        paid = store.find_subject_sheet("选配金统计", subject.name, suffix=PAID_ALIASES)
        candidates = store.matching_sheet_names("选配金统计", subject.name)
        if not penetration:
            LOGGER.warning("品牌选配金未匹配到渗透率排名Sheet: 主体=%s；候选=%s", subject.name, candidates or "无")
            return None
        item, penetration_sheet = penetration
        penetration_source = SourceRef(item.path.name, penetration_sheet.title, "品牌渗透率排名")
        paid_source = SourceRef(paid[0].path.name, paid[1].title, "品牌付费项排名") if paid else None
        if not paid:
            LOGGER.warning("品牌 %s 未匹配到付费选配Sheet，将使用渗透率排名和代际明细继续生成；候选=%s", subject.name, candidates or "无")
        else:
            LOGGER.debug("品牌选配金映射成功: %s -> %s / %s", subject.name, penetration_sheet.title, paid[1].title)

        cards: dict[str, list[dict]] = defaultdict(list)
        current_generation = ""
        summary_col = _summary_column(penetration_sheet)
        for row in range(3, penetration_sheet.max_row + 1):
            generation = clean_text(penetration_sheet.cell(row, 1).value)
            if generation:
                current_generation = generation
            rank = int(safe_number(penetration_sheet.cell(row, 2).value))
            item_data = _parse_rank_item(penetration_sheet.cell(row, summary_col).value)
            if current_generation and rank and item_data:
                cards[current_generation].append({"rank": rank, **item_data})
        if not cards:
            LOGGER.warning("品牌选配金Sheet已匹配但没有读取到排名记录: %s / %s", subject.name, penetration_sheet.title)
            return None

        band_rows, option_values, generation_sources = [], [], []
        collected_bands: list[str] = []
        paid_orders = total_orders = 0.0
        for sheet in item.workbook.worksheets:
            generation = sheet_subject(sheet.title)
            normalized_title = compact_identifier(sheet.title)
            if "选配渗透率" not in normalized_title or "排名" in normalized_title or generation not in cards:
                continue
            if is_aggregate_generation(generation):
                # 品牌级统计不重复纳入“总计/汇总”代际，避免与明细代际重复计算。
                continue
            try:
                _, band_row, order_row = _option_layout(sheet)
                periods, groups = _period_groups(sheet)
            except ValueError as exc:
                LOGGER.warning("代际选配金表头识别失败: 代际=%s Sheet=%s 原因=%s，已跳过该Sheet", generation, sheet.title, exc)
                continue
            # 每个代际的金额段分档可能不同（5000元档 / 10000元档），按该Sheet实际段名动态收集
            sheet_bands: list[str] = []
            for period in periods:
                for _, band in groups[period]:
                    if band not in sheet_bands:
                        sheet_bands.append(band)
            for band in sheet_bands:
                if band not in collected_bands:
                    collected_bands.append(band)
            LOGGER.debug(
                "代际金额段解析: %s / %s periods=%s 段列=%s",
                item.path.name, sheet.title, periods,
                {period: [(col, band, sheet.cell(order_row, col).value) for col, band in groups[period]] for period in periods},
            )
            totals = {band: 0.0 for band in sheet_bands}
            for period in periods:
                for col, band in groups[period]:
                    totals[band] += safe_number(sheet.cell(order_row, col).value)
            LOGGER.debug("代际金额段合计: %s -> %s", generation, totals)
            paid_bands = [band for band in sheet_bands if "免费" not in band]
            if totals.get("免费", 0) > 0 and all(totals.get(band, 0) == 0 for band in paid_bands):
                raw_bands = [clean_text(sheet.cell(band_row, col).value) for col in range(3, sheet.max_column + 1)]
                raw_bands = [band for band in raw_bands if band]
                LOGGER.warning(
                    "金额段疑似异常(只有免费段有值): 代际=%s Sheet=%s 各段=%s | row4原始段名=%s | 识别段列=%s",
                    generation, sheet.title, totals, raw_bands,
                    {period: [(col, band) for col, band in groups[period]] for period in periods},
                )
            band_rows.append({"label": generation, "totals": totals, "bands": sheet_bands})
            paid_orders += sum(totals.get(band, 0) for band in paid_bands)
            total_orders += sum(totals.values())
            _, sheet_options, _ = _amount_rows(sheet)
            option_values.extend(sheet_options)
            generation_sources.append(SourceRef(item.path.name, sheet.title, "代际金额段结构"))
        if not band_rows:
            LOGGER.warning("品牌 %s 已生成高频选配项，但没有匹配到代际选配金额段明细", subject.name)

        # 品牌页统一按所有代际的段并集展示，缺失的段记 0
        unified_bands = [band for band in BAND_ORDER if band in collected_bands] + [band for band in collected_bands if band not in BAND_ORDER]
        band_values = [
            {"label": row["label"], "values": [row["totals"].get(band, 0) for band in unified_bands]}
            for row in band_rows
        ]

        top_pen_label, top_pen_rate = "—", 0.0
        for items in cards.values():
            for item_data in items:
                if item_data.get("rank") == 1 and item_data.get("rate", 0) > top_pen_rate:
                    top_pen_rate = item_data["rate"]
                    top_pen_label = item_data["label"]

        page = {
            "kpis": [
                kpi("覆盖代际", len(cards), "个", "品牌汇总", "blue"),
                kpi("平均选配金额", round(sum(option_values) / len(option_values)) if option_values else 0, "元", "版本均值", "green"),
                kpi("付费选配占比", round(paid_orders / total_orders * 100) if total_orders else 0, "%", "付费金额段订单占比", "orange"),
                kpi("TOP选配渗透率", round(top_pen_rate * 100), "%", top_pen_label, "purple"),
            ],
            "sections": [
                section("rank_cards", "各代际高频选配项", cards, "总计口径 TOP 排名", source=penetration_source),
                section("fee_band_structure", "各代际选配金额段结构", {"bands": unified_bands, "rows": band_values}, "订单量占比 · 不同代际分档不同", source=generation_sources[0] if generation_sources else (paid_source or penetration_source)),
            ],
        }
        views = {"month": {"periods": ["汇总"], "default_period": "汇总", "pages": {"汇总": page}}}
        sources = [penetration_source, *([paid_source] if paid_source else []), *generation_sources]
        return Dashboard(self.id, subject.id, views, sources)

    def _build_generation(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        penetration = store.find_subject_sheet("选配金统计", subject.name, suffix=PENETRATION_ALIASES)
        paid = store.find_subject_sheet("选配金统计", subject.name, suffix=PAID_ALIASES)
        candidates = store.matching_sheet_names("选配金统计", subject.name)
        if not penetration:
            LOGGER.warning("代际选配金未匹配到渗透率Sheet: 主体=%s；候选=%s", subject.name, candidates or "无")
            return None
        item, sheet = penetration
        penetration_source = SourceRef(item.path.name, sheet.title, "选配渗透率")
        paid_sheet = paid[1] if paid else None
        paid_source = SourceRef(paid[0].path.name, paid_sheet.title, "付费选配占比") if paid else None
        if not paid:
            LOGGER.warning("代际 %s 未匹配到付费选配Sheet，人均付费项将显示为0；候选=%s", subject.name, candidates or "无")
        rights_amount, rights_text = _rights(sheet)
        try:
            _, _, order_row = _option_layout(sheet)
            periods, groups = _period_groups(sheet)
        except ValueError as exc:
            LOGGER.warning("代际选配金表头识别失败: 主体=%s Sheet=%s 原因=%s", subject.name, sheet.title, exc)
            return None

        sheet_bands: list[str] = []
        for period in periods:
            for _, band in groups[period]:
                if band not in sheet_bands:
                    sheet_bands.append(band)

        band_series = []
        for band in sheet_bands:
            values = []
            for period in periods:
                col = next((col for col, label in groups[period] if label == band), None)
                values.append(safe_number(sheet.cell(order_row, col).value) if col else 0)
            band_series.append({"name": band, "values": values})

        penetration_rows, current_group = [], ""
        for row in range(order_row + 1, sheet.max_row + 1):
            group = clean_text(sheet.cell(row, 1).value)
            if group:
                current_group = group
            if not current_group or subject.name in current_group:
                continue
            label = clean_text(sheet.cell(row, 2).value)
            if not label or label in {"选配金额", "实际金额"}:
                continue
            values = []
            for period in periods:
                weighted = orders = 0.0
                for col, _ in groups[period]:
                    count = safe_number(sheet.cell(order_row, col).value)
                    weighted += cell_number(sheet.cell(row, col), rate=True) * count
                    orders += count
                values.append(safe_rate(weighted, orders))
            penetration_rows.append({"group": current_group, "label": label, "values": values})

        paid_items_by_period: dict[str, list[tuple[str, float]]] = {period: [] for period in periods}
        if paid_sheet:
            try:
                _, _, paid_order_row = _option_layout(paid_sheet)
                paid_periods, paid_groups = _period_groups(paid_sheet)
            except ValueError as exc:
                LOGGER.warning("付费选配表头识别失败: 主体=%s Sheet=%s 原因=%s，付费项排名将留空", subject.name, paid_sheet.title, exc)
                paid_periods, paid_groups, paid_order_row = [], {}, 0
            for row in range(paid_order_row + 1, paid_sheet.max_row + 1) if paid_order_row else ():
                label = clean_text(paid_sheet.cell(row, 2).value)
                if not label or label in {"选配金额", "实际金额"}:
                    continue
                for period in periods:
                    weighted = orders = 0.0
                    for col, _ in paid_groups.get(period, []):
                        count = safe_number(paid_sheet.cell(paid_order_row, col).value)
                        weighted += cell_number(paid_sheet.cell(row, col), rate=True) * count
                        orders += count
                    paid_items_by_period[period].append((label, safe_rate(weighted, orders)))

        totals_by_period = _totals_by_period(sheet, periods)
        version_rows_by_period = _version_rows_by_period(sheet, periods)
        latest = periods[-1] if periods else "汇总"
        option_total, actual_total = totals_by_period.get(latest, (0.0, 0.0))
        top_paid = max(paid_items_by_period.get(latest, []), key=lambda item: item[1], default=("—", 0.0))
        version_rows = version_rows_by_period.get(latest, [])
        # 与SKU收敛度一致:下拉只显示最新月,图表展示所有月,KPI/版本表取最新月
        page = {
            "kpis": [
                kpi("平均选配金额", round(option_total), "元", f"{latest} 合计口径", "blue"),
                kpi("平均实际金额", round(actual_total), "元", f"{latest} 合计口径", "green"),
                kpi("最高付费选配占比", round(top_paid[1] * 100), "%", top_paid[0], "orange"),
                kpi("权益金额", round(rights_amount), "元", "当前权益", "purple"),
            ],
            "sections": [
                section("fee_period_bands", "价格敏感度分析", {"periods": periods, "series": band_series, "actual_total": actual_total}, "月度选配金额段结构 · 实际金额总计", "half", penetration_source),
                section("fee_heatmap", "选配项渗透率热力图", {"periods": periods, "rows": penetration_rows}, "月度变化", "half", penetration_source),
                section("rights", "当前权益", {"amount": rights_amount, "text": rights_text}, "代际专属权益", "half", penetration_source),
                section("table", "版本选配金额与实际金额", table(["版本", "选配金额", "实际金额", "权益抵扣率"], version_rows, formats=["text", "number", "number", "percent"]), f"{latest} 权益抵扣效果", "half", penetration_source),
            ],
        }
        views = {"month": {"periods": [latest], "default_period": latest, "pages": {latest: page}}}
        return Dashboard(self.id, subject.id, views, [penetration_source, *([paid_source] if paid_source else [])])
