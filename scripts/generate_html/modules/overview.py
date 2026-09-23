from __future__ import annotations

import logging
import re

from core.components import kpi, section
from core.discovery import BRAND_ORDER
from core.excel import GRAIN_LABELS, WorkbookStore, grain_from_sheet, is_aggregate_generation, parse_metric_sheet, sheet_subject, subject_parent, subject_type
from core.models import Dashboard, SourceRef, Subject


COLORS = ["blue", "green", "orange", "purple"]
HISTORY_COLUMNS = ["周期", "大定", "环比", "留存大定", "环比", "交车锁单", "环比", "已交付", "环比"]
HISTORY_FORMATS = ["text", "number", "signed_percent", "number", "signed_percent", "number", "signed_percent", "number", "signed_percent"]
LOGGER = logging.getLogger(__name__)
AGGREGATE_MARKERS = ("近", "汇总", "累计", "总计")
MODEL_YEAR_PATTERN = re.compile(r"20\d{2}\s*款")


def _latest_detail_period(periods: list[str]) -> str:
    """默认展示最新的日期/周/月。"""
    return next(
        (period for period in reversed(periods) if not any(marker in str(period) for marker in AGGREGATE_MARKERS)),
        periods[-1],
    )


def _metric_value(metrics: dict, *names: str) -> float:
    return next((metrics[name] for name in names if name in metrics), 0)


def _group_model_series(store: WorkbookStore, grain: str) -> dict[str, dict[str, dict]]:
    """读取鸿蒙智行下各车型最新年款的同期留存大定、交车锁单序列。"""
    names = {
        subject_name
        for _, sheet_name in store.all_sheet_names()
        if "图表" not in sheet_name
        and (subject_name := sheet_subject(sheet_name))
        and subject_type(subject_name) == "generation"
        and not is_aggregate_generation(subject_name)
    }

    def sort_key(name: str) -> tuple[int, str]:
        brand = subject_parent(name, "generation")
        return (BRAND_ORDER.index(brand) if brand in BRAND_ORDER else len(BRAND_ORDER), name)

    candidates = {}
    latest_years: dict[str, int] = {}
    for name in sorted(names, key=sort_key):
        order_found = store.find_subject_sheet("大定选配比例", name, grain)
        lock_found = store.find_subject_sheet("锁单选配比例", name, grain)
        if not order_found or not lock_found:
            continue
        candidates[name] = (order_found[1], lock_found[1])
        match = MODEL_YEAR_PATTERN.search(name)
        if match:
            model_key = re.sub(r"\s+", "", MODEL_YEAR_PATTERN.sub("", name, count=1)).casefold()
            latest_years[model_key] = max(latest_years.get(model_key, 0), int(match.group()[:4]))
    series: dict[str, dict[str, dict]] = {}
    for name, (order_sheet, lock_sheet) in candidates.items():
        match = MODEL_YEAR_PATTERN.search(name)
        if match:
            model_key = re.sub(r"\s+", "", MODEL_YEAR_PATTERN.sub("", name, count=1)).casefold()
            if int(match.group()[:4]) < latest_years[model_key]:
                continue
        series[name] = {
            "留存大定": parse_metric_sheet(order_sheet),
            "交车锁单": parse_metric_sheet(lock_sheet),
        }
    return series


def _change_rankings(
    model_series: dict[str, dict[str, dict]],
    period: str,
    previous_period: str | None,
    direction: str,
) -> dict[str, list[dict]]:
    """按环比涨跌幅生成留存大定、交车锁单两张车型榜。"""
    if previous_period is None:
        return {}
    rankings: dict[str, list[dict]] = {}
    for metric in ("留存大定", "交车锁单"):
        rows = []
        for name, series in model_series.items():
            current_metrics = series[metric].get(period, {}).get("metrics", {})
            previous_metrics = series[metric].get(previous_period, {}).get("metrics", {})
            aliases = ("留存大定", "净大定") if metric == "留存大定" else (metric,)
            current = _metric_value(current_metrics, *aliases)
            previous = _metric_value(previous_metrics, *aliases)
            if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)) or previous <= 0:
                continue
            if direction == "rise":
                if current <= previous:
                    continue
                rate = (current - previous) / previous
            else:
                if current >= previous:
                    continue
                rate = (previous - current) / previous
            rows.append({"label": name, "rate": rate})
        rows.sort(key=lambda row: (-row["rate"], row["label"]))
        if rows:
            rankings[metric] = [
                {"rank": index, **row}
                for index, row in enumerate(rows[:10], start=1)
            ]
    return rankings


def _drop_rankings(
    model_series: dict[str, dict[str, dict]],
    period: str,
    previous_period: str | None,
) -> dict[str, list[dict]]:
    """按环比跌幅降序生成留存大定、交车锁单两张车型榜。"""
    return _change_rankings(model_series, period, previous_period, "drop")


def _rise_rankings(
    model_series: dict[str, dict[str, dict]],
    period: str,
    previous_period: str | None,
) -> dict[str, list[dict]]:
    """按环比涨幅降序生成留存大定、交车锁单两张车型榜。"""
    return _change_rankings(model_series, period, previous_period, "rise")


def _chart_metric(chart_data: dict | None, candidates: tuple[str, ...]) -> str | None:
    headline = str((chart_data or {}).get("headline") or "")
    return next((metric for metric in candidates if metric in headline), None)


def _chart_totals(chart_data: dict | None) -> dict[str, float]:
    if not chart_data:
        return {}
    return {
        str(period): total
        for period, total in zip(chart_data.get("periods", []), chart_data.get("totals", []))
        if isinstance(total, (int, float))
    }


def _lock_trend(lock_data: dict, periods: list[str], subject: Subject, grain: str) -> dict:
    """Build the lock-order trend from the subject's own lock sheet."""
    labels: list[str] = []
    for period in periods:
        for row in lock_data[period].get("structures", {}).get("动力", []):
            label = str(row.get("label") or "")
            if label and label not in labels:
                labels.append(label)
    totals = [
        lock_data[period].get("metrics", {}).get("交车锁单", 0)
        for period in periods
    ]
    if labels:
        series = [
            {
                "name": label,
                "values": [
                    next(
                        (
                            row.get("share", 0)
                            for row in lock_data[period].get("structures", {}).get("动力", [])
                            if str(row.get("label") or "") == label
                        ),
                        0,
                    )
                    for period in periods
                ],
            }
            for label in labels
        ]
    else:
        series = [{"name": "交车锁单", "values": [1.0 if total else 0.0 for total in totals]}]
    return {
        "subject": subject.name,
        "headline": f"{subject.name}{GRAIN_LABELS[grain]}交车锁单",
        "periods": periods,
        "series": series,
        "totals": totals,
        "image_key": None,
    }


def _period_metric_values(
    order_data: dict,
    lock_data: dict,
    period: str,
    order_chart: dict | None = None,
    lock_chart: dict | None = None,
    use_chart_totals: bool = False,
) -> list[float]:
    """大定/已交付取数据Sheet，留存大定/交车锁单按图表Sheet标题覆盖。"""
    order_row = order_data[period]["metrics"]
    lock_row = lock_data[period]["metrics"]
    values = {
        "大定": order_row.get("大定", 0),
        "留存大定": _metric_value(order_row, "留存大定", "净大定"),
        "交车锁单": lock_row.get("交车锁单", 0),
        "已交付": lock_row.get("已交付", 0),
    }
    if use_chart_totals:
        order_metric = "留存大定" if any(name in str((order_chart or {}).get("headline") or "") for name in ("留存大定", "净大定")) else _chart_metric(order_chart, ("大定",))
        lock_metric = _chart_metric(lock_chart, ("交车锁单", "已交付"))
        if order_metric and period in (totals := _chart_totals(order_chart)):
            values[order_metric] = totals[period]
        if lock_metric and period in (totals := _chart_totals(lock_chart)):
            values[lock_metric] = totals[period]
    return [values["大定"], values["留存大定"], values["交车锁单"], values["已交付"]]


def _history_rows(
    order_data: dict,
    lock_data: dict,
    periods: list[str],
    order_chart: dict | None = None,
    lock_chart: dict | None = None,
    use_chart_totals: bool = False,
) -> list[list]:
    """按当前主体的图表与数据Sheet生成明细周期经营表现行。"""
    previous_values = None
    rows = []
    for name in periods:
        metric_values = _period_metric_values(
            order_data, lock_data, name, order_chart, lock_chart, use_chart_totals,
        )
        row = [name]
        for index, value in enumerate(metric_values):
            row.append(value)
            if previous_values is not None and previous_values[index]:
                row.append((value - previous_values[index]) / abs(previous_values[index]))
            else:
                row.append("—")
        rows.append(row)
        previous_values = metric_values
    return rows


def _lock_share_rows(
    store: WorkbookStore,
    subject: Subject,
    grain: str,
    period: str,
    issues: list[tuple[str, str, tuple[str, ...]]] | None = None,
    display_total: float | None = None,
) -> tuple[str, list[dict]] | tuple[None, None]:
    """按主体层级聚合交车锁单占比：集团->品牌，品牌->代际，代际->版本。"""
    if subject.type in ("group", "brand"):
        names: set[str] = set()
        # Only lock-order workbooks define the child set for this chart. Discovering
        # generations from unrelated files made one missing lock sheet hide the
        # entire brand chart, even when every available lock source was complete.
        for item in store.find_all("锁单选配比例"):
            for sheet_name in item.workbook.sheetnames:
                if "图表" in sheet_name or grain_from_sheet(sheet_name) != grain:
                    continue
                subj = sheet_subject(sheet_name)
                if not subj or is_aggregate_generation(subj):
                    continue
                if subject.type == "group" and subj in BRAND_ORDER:
                    names.add(subj)
                elif subject.type == "brand" and subject_type(subj) == "generation" and subject_parent(subj, "generation") == subject.name:
                    names.add(subj)
        if subject.type == "group":
            ordered = [name for name in BRAND_ORDER if name in names] + sorted(names - set(BRAND_ORDER))
        else:
            ordered = sorted(names)
        rows = []
        missing_sources: list[str] = []
        for name in ordered:
            found = store.find_subject_sheet("锁单选配比例", name, grain)
            if not found:
                missing_sources.append(name)
                continue
            parsed = parse_metric_sheet(found[1])
            # 锁单明细是稀疏周期表：某日/周/月没有卖出车辆时，该周期列可能完全不出现。
            # 只要主体Sheet存在，同期周期缺失就代表0，而不是数据缺失。
            count = parsed.get(period, {}).get("metrics", {}).get("交车锁单", 0)
            rows.append({"label": name, "share": 0.0, "count": count})
        if missing_sources:
            if issues is not None:
                issues.append(("child_source", period, tuple(missing_sources)))
            else:
                LOGGER.warning(
                    "[总览口径校验] 主体=%s | 粒度=%s | 周期=%s | 子主体缺少锁单Sheet=%s | "
                    "处理=不展示不完整的占比图，不用其他周期回退",
                    subject.name, grain, period, "、".join(missing_sources),
                )
            return None, None
        if not rows:
            return None, None
        total = sum(row["count"] for row in rows)
        if total <= 0:
            return None, None
        for row in rows:
            row["share"] = row["count"] / total
        if subject.type == "group" and display_total is not None and display_total >= 0:
            # Preserve the child-sheet brand mix while matching the channel chart total.
            # Largest-remainder allocation keeps integer counts and an exact total.
            target = int(round(display_total))
            exact_counts = [row["share"] * target for row in rows]
            display_counts = [int(value) for value in exact_counts]
            remainder = target - sum(display_counts)
            allocation_order = sorted(
                range(len(rows)),
                key=lambda index: (-(exact_counts[index] - display_counts[index]), index),
            )
            for index in allocation_order[:remainder]:
                display_counts[index] += 1
            for row, count in zip(rows, display_counts):
                row["count"] = count
        title = "各品牌交车锁单占比" if subject.type == "group" else "各代际交车锁单占比"
        return title, rows
    found = store.find_subject_sheet("锁单选配比例", subject.name, grain)
    if not found:
        return None, None
    parsed = parse_metric_sheet(found[1])
    if period not in parsed:
        if issues is not None:
            issues.append(("version", period, ()))
        else:
            LOGGER.warning(
                "[总览口径校验] 主体=%s | 粒度=%s | 周期=%s | 缺少同期版本锁单结构 | "
                "处理=不展示占比图，不用其他周期回退",
                subject.name, grain, period,
            )
        return None, None
    version_rows = parsed[period].get("structures", {}).get("版本")
    if not version_rows:
        return None, None
    rows = [{"label": row["label"], "share": row["share"], "count": row.get("count")} for row in version_rows]
    return "各版本交车锁单占比", rows


def _period_range_text(periods: list[str], ordered_periods: list[str]) -> str:
    """按页面周期顺序把连续异常压缩为范围，避免逐周期刷日志。"""
    selected = set(periods)
    ranges: list[list[str]] = []
    current: list[str] = []
    for period in ordered_periods:
        if period in selected:
            current.append(period)
        elif current:
            ranges.append(current)
            current = []
    if current:
        ranges.append(current)
    labels = [
        group[0] if len(group) == 1 else f"{group[0]}–{group[-1]}（{len(group)}期）"
        for group in ranges
    ]
    return "、".join(labels)


def _log_lock_share_issues(
    subject: Subject,
    grain: str,
    ordered_periods: list[str],
    issues: list[tuple[str, str, tuple[str, ...]]],
) -> None:
    if not issues:
        return
    details: list[str] = []
    missing_source_periods: dict[str, list[str]] = {}
    version_periods: list[str] = []
    for kind, period, detail in issues:
        if kind == "child_source":
            for name in detail:
                missing_source_periods.setdefault(name, []).append(period)
        elif kind == "version":
            version_periods.append(period)
    if missing_source_periods:
        rendered = "、".join(
            f"{name}（{_period_range_text(periods, ordered_periods)}）"
            for name, periods in missing_source_periods.items()
        )
        details.append(f"子主体缺少锁单Sheet={rendered}")
    if version_periods:
        details.append(f"缺少同期版本结构={_period_range_text(version_periods, ordered_periods)}")
    if details:
        LOGGER.warning(
            "[总览口径校验] 主体=%s | 粒度=%s | 异常=%s | "
            "处理=仅隐藏异常周期占比图；稀疏周期按0处理，不用其他周期回退",
            subject.name, grain, "；".join(details),
        )


class OverviewModule:
    id = "overview"
    label = "订单总览"

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        grains_data: dict[str, dict] = {}
        sources: list[SourceRef] = []
        for grain in ("day", "week", "month"):
            order_found = store.find_subject_sheet("大定选配比例", subject.name, grain)
            lock_found = store.find_subject_sheet("锁单选配比例", subject.name, grain)
            if not order_found or not lock_found:
                continue
            order_item, order_sheet = order_found
            lock_item, lock_sheet = lock_found
            order_data = parse_metric_sheet(order_sheet)
            lock_data = parse_metric_sheet(lock_sheet)
            periods = [
                period
                for period in order_data
                if period in lock_data and not any(marker in str(period) for marker in AGGREGATE_MARKERS)
            ]
            if not periods:
                continue
            order_chart = store.find_chart_data("大定选配比例", subject.name, grain)
            lock_chart = store.find_chart_data("锁单选配比例", subject.name, grain)
            order_chart_data = None
            if order_chart:
                order_chart_data = dict(order_chart[2])
                order_chart_data["headline"] = str(order_chart_data.get("headline") or "").replace("净大定", "留存大定")
            order_source = SourceRef(order_item.path.name, order_sheet.title, "大定与留存大定")
            lock_source = SourceRef(lock_item.path.name, lock_sheet.title, "交车锁单与已交付")
            order_chart_source = SourceRef(order_chart[0].path.name, order_chart[1].title, "留存大定趋势") if order_chart else order_source
            lock_chart_source = SourceRef(lock_chart[0].path.name, lock_chart[1].title, "交车锁单趋势") if lock_chart else lock_source
            grains_data[grain] = {
                "periods": periods,
                "order": order_data,
                "lock": lock_data,
                "order_chart": order_chart_data,
                "lock_chart": lock_chart[2] if lock_chart else _lock_trend(lock_data, periods, subject, grain),
                "order_chart_source": order_chart_source,
                "lock_chart_source": lock_chart_source,
                "order_source": order_source,
                "lock_source": lock_source,
            }
            sources.extend([order_source, lock_source])
            if order_chart:
                sources.append(SourceRef(order_chart[0].path.name, order_chart[1].title, "留存大定趋势"))
            if lock_chart:
                sources.append(SourceRef(lock_chart[0].path.name, lock_chart[1].title, "交车锁单趋势"))
        if not grains_data:
            return None

        # 经营指标趋势直接读取当前主体：大定/已交付来自数据Sheet，留存大定/交车锁单来自图表Sheet。
        # “汇总代际”只在子主体型板块过滤，不参与集团/品牌 KPI 与趋势的计算。
        history_options = {
            grain: {
                "columns": HISTORY_COLUMNS,
                "formats": HISTORY_FORMATS,
                "rows": _history_rows(
                    gd["order"], gd["lock"], gd["periods"],
                    gd["order_chart"], gd["lock_chart"],
                    True,
                ),
            }
            for grain, gd in grains_data.items()
            if grain in ("week", "month")
        }

        views = {}
        for grain, gd in grains_data.items():
            periods = gd["periods"]
            order_data = gd["order"]
            lock_data = gd["lock"]
            model_series = _group_model_series(store, grain) if subject.type == "group" else {}
            pages = {}
            lock_share_issues: list[tuple[str, str, tuple[str, ...]]] = []
            for period in periods:
                order = order_data[period]
                lock = lock_data[period]
                values = list(zip(
                    ("大定", "留存大定", "交车锁单", "已交付"),
                    _period_metric_values(
                        order_data, lock_data, period,
                        gd["order_chart"], gd["lock_chart"],
                        True,
                    ),
                ))
                channels = lock["structures"].get("门店类型", [])
                channel_counts = [row.get("count") for row in channels]
                channel_total = (
                    sum(float(count) for count in channel_counts)
                    if channel_counts and all(isinstance(count, (int, float)) for count in channel_counts)
                    else None
                )
                share_title, share_rows = _lock_share_rows(
                    store,
                    subject,
                    grain,
                    period,
                    lock_share_issues,
                    channel_total,
                )
                pages[period] = {
                    "kpis": [
                        *[kpi(label, value, "单", period, COLORS[index]) for index, (label, value) in enumerate(values)],
                    ],
                    "sections": [
                        section("stacked_trend", f"{subject.name}{GRAIN_LABELS[grain]}度留存大定趋势", gd["order_chart"], "图表Sheet", "half", gd["order_chart_source"]),
                        section(
                            "stacked_trend",
                            f"{subject.name}{GRAIN_LABELS[grain]}度交车锁单趋势",
                            gd["lock_chart"], "图表Sheet", "half", gd["lock_chart_source"],
                        ),
                        section("bars", "门店渠道订单量", {"color": "green", "rows": channels}, "交车锁单数量", "half", gd["lock_source"]),
                        section("history_table", "经营指标趋势", {"granularities": history_options, "default": grain}, "全部明细周期 · 环比涨跌幅", "full", gd["order_source"]),
                    ],
                }
                if share_title and share_rows:
                    pages[period]["sections"].insert(2, section(
                        "donut", share_title, {"color": "blue", "rows": share_rows}, "交车锁单口径", "half", gd["lock_source"],
                    ))
                if model_series and not any(marker in str(period) for marker in AGGREGATE_MARKERS):
                    period_index = periods.index(period)
                    previous_period = next(
                        (
                            candidate
                            for candidate in reversed(periods[:period_index])
                            if not any(marker in str(candidate) for marker in AGGREGATE_MARKERS)
                        ),
                        None,
                    )
                    rise_rankings = _rise_rankings(model_series, period, previous_period)
                    drop_rankings = _drop_rankings(model_series, period, previous_period)
                    if drop_rankings:
                        pages[period]["sections"].insert(2, section(
                            "drop_rank_cards",
                            "车型留存大定与交车锁单跌幅排行",
                            drop_rankings,
                            f"较上一{ {'day': '日', 'week': '周', 'month': '月'}[grain] } · 仅展示环比下降车型",
                            "full",
                            gd["lock_source"],
                        ))
                    if rise_rankings:
                        pages[period]["sections"].insert(2, section(
                            "rise_rank_cards",
                            "车型留存大定与交车锁单涨幅排行",
                            rise_rankings,
                            f"较上一{ {'day': '日', 'week': '周', 'month': '月'}[grain] } · 仅展示环比上升车型",
                            "full",
                            gd["lock_source"],
                        ))
            _log_lock_share_issues(subject, grain, periods, lock_share_issues)
            views[grain] = {"periods": periods, "default_period": _latest_detail_period(periods), "pages": pages}
        return Dashboard(self.id, subject.id, views, sources) if views else None
