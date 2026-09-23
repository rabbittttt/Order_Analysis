from __future__ import annotations

import re

from core.components import kpi, section, table
from core.excel import WorkbookStore, parse_metric_sheet
from core.models import Dashboard, SourceRef, Subject


def _latest_detail_period(periods: list[str]) -> str:
    """默认展示最新明细周期，总计/汇总仍保留在下拉选项中。"""
    aggregate_markers = ("近", "汇总", "累计", "总计")
    return next(
        (period for period in reversed(periods) if not any(marker in str(period) for marker in aggregate_markers)),
        periods[-1],
    )


def _battery_degree(label: str) -> int:
    """电池包选项按度数升序排序；无数字的排最后。"""
    match = re.search(r"\d+", label)
    return int(match.group()) if match else 10**9


def _battery_history(parsed: dict, periods: list[str]) -> dict | None:
    """构建电池包度数环比表(类似最近周期经营表现):行=周期,列=各度数+环比。"""
    labels: list[str] = []
    for period in periods:
        for row in parsed[period].get("structures", {}).get("电池包", []):
            if row["label"] not in labels:
                labels.append(row["label"])
    if not labels:
        return None
    labels.sort(key=_battery_degree)
    columns = ["周期"]
    for label in labels:
        columns.extend([label, "环比"])
    formats = ["text"]
    for _ in labels:
        formats.extend(["percent", "signed_percent"])
    previous_shares: dict[str, float] | None = None
    rows = []
    for period in periods:
        share_map = {row["label"]: row["share"] for row in parsed[period].get("structures", {}).get("电池包", [])}
        row: list = [period]
        for label in labels:
            value = share_map.get(label, 0)
            row.append(value)
            if previous_shares is not None and previous_shares.get(label):
                row.append((value - previous_shares[label]) / abs(previous_shares[label]))
            else:
                row.append("—")
        rows.append(row)
        previous_shares = share_map
    return {"columns": columns, "formats": formats, "rows": rows}


class MixModule:
    def __init__(self, kind: str):
        self.kind = kind
        settings = {
            "order": ("order_mix", "大定选配", "大定选配比例", "大定", "留存大定"),
            "lock": ("lock_mix", "锁单选配", "锁单选配比例", "交车锁单", "已交付"),
            "small": ("small_order_mix", "小订选配", "小订选配比例", "小订", "留存小订"),
        }
        self.id, self.label, self.keyword, self.primary, self.secondary = settings[kind]

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        grains_data: dict[str, dict] = {}
        sources: list[SourceRef] = []
        for grain in ("day", "week", "month"):
            found = store.find_subject_sheet(self.keyword, subject.name, grain)
            if not found:
                continue
            item, sheet = found
            parsed = parse_metric_sheet(sheet)
            periods = list(parsed)
            if not periods:
                continue
            data_source = SourceRef(item.path.name, sheet.title, self.label)
            grains_data[grain] = {
                "parsed": parsed,
                "periods": periods,
                "source": data_source,
            }
            sources.append(data_source)
        if not grains_data:
            return None

        # 电池包度数环比表:周/月两个粒度各一份全量数据,由顶部粒度统一切换
        battery_options = {
            grain: history
            for grain, gd in grains_data.items()
            if grain in ("week", "month") and (history := _battery_history(gd["parsed"], gd["periods"]))
        }

        views = {}
        for grain, gd in grains_data.items():
            parsed = gd["parsed"]
            periods = gd["periods"]
            data_source = gd["source"]
            pages = {}
            previous = None
            for period in periods:
                data = parsed[period]
                structures = []
                for name, rows in data["structures"].items():
                    previous_rows = (previous or {}).get("structures", {}).get(name, [])
                    prev_map = {row["label"]: row["share"] for row in previous_rows}
                    ordered_rows = (
                        sorted(rows, key=lambda entry: _battery_degree(entry["label"]))
                        if "电池包" in name
                        else sorted(rows, key=lambda entry: entry["share"], reverse=True)
                    )
                    items = []
                    for rank, row in enumerate(ordered_rows, start=1):
                        current_share = row["share"]
                        prior_share = prev_map.get(row["label"], current_share)
                        items.append({**row, "previous": prior_share, "change": current_share - prior_share, "rank": rank})
                    structures.append({"name": name, "rows": items})
                all_rows = [
                    {**row, "structure": group["name"]}
                    for group in structures for row in group["rows"]
                ]
                leaders = []
                for group in structures:
                    if not group["rows"]:
                        continue
                    leader = dict(max(group["rows"], key=lambda row: row["share"]))
                    leader["structure"] = group["name"]
                    leaders.append(leader)
                leading_share = max((row["share"] for row in leaders), default=0)
                dimension_count = len(structures)
                option_count = sum(len(group["rows"]) for group in structures)
                focused_dimensions = sum(1 for row in leaders if row["share"] >= 0.5)
                max_change = max((abs(row["change"]) for row in all_rows), default=0)
                leader_bars = [
                    {"label": f'{row["structure"]} · {row["label"]}', "share": row["share"], "count": row.get("count")}
                    for row in leaders
                ]
                change_rows = [
                    [row["structure"], row["label"], row["share"], row["previous"], row["change"], row.get("count")]
                    for row in sorted(all_rows, key=lambda row: abs(row["change"]), reverse=True)[:18]
                ]
                sections = [
                    section("structure_cards", "选配结构全景", structures, "选配占比 / 环比变化", source=data_source),
                    section("bars", "各维度首选配置", {"color": "blue", "rows": leader_bars}, "每个选配维度 TOP1", "half", data_source),
                    section("table", "选配偏好变化排行", table(
                        ["选配维度", "配置", "本期占比", "上期占比", "变化", "选配数"],
                        change_rows,
                        formats=["text", "text", "percent", "percent", "signed_percent", "number"],
                    ), "按选配占比变化绝对值排序", "half", data_source),
                ]
                if battery_options.get(grain):
                    sections.append(section(
                        "history_table",
                        "电池包度数环比",
                        {"granularities": battery_options, "default": grain},
                        "全部周期 · 各度数选配占比环比变化",
                        "full",
                        data_source,
                    ))
                pages[period] = {
                    "kpis": [
                        kpi("选配维度", dimension_count, "个", "外观 / 内饰 / 版本等", "blue"),
                        kpi("活跃选配项", option_count, "项", "当前周期有数据", "green"),
                        kpi("领先配置占比", leading_share * 100, "%", "跨维度最高", "orange"),
                        kpi("高集中维度", focused_dimensions, "个", "TOP1占比≥50%", "purple"),
                        kpi("最大结构变化", max_change * 100, "个百分点", "较上周期", "coral"),
                    ],
                    "sections": sections,
                }
                previous = data
            views[grain] = {"periods": periods, "default_period": _latest_detail_period(periods), "pages": pages}
        return Dashboard(self.id, subject.id, views, sources) if views else None


class OrderMixModule(MixModule):
    def __init__(self):
        super().__init__("order")


class LockMixModule(MixModule):
    def __init__(self):
        super().__init__("lock")


class SmallOrderMixModule(MixModule):
    def __init__(self):
        super().__init__("small")
