"""Read forecast inputs from one workbook while retaining original source identities."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook

from core.excel import WorkbookItem, WorkbookStore

SUMMARY_NAME = "鸿蒙智行销量数据汇总.xlsx"
GUIDE_SHEET = "说明与来源"
MASTER_SHEET = "车型基本信息"
DAILY_SHEET = "小订首销平销by天"
SMALL_HOURLY_SHEET = "小订by时"
LAUNCH_HOURLY_SHEET = "首销by时"
WEEKLY_SHEET = "首销平销by周"
INDEX_SHEET = "数据来源目录"
SNAPSHOT_SHEET = "_预测缓存"
ACTIVE_SUMMARY = ContextVar("forecast_summary", default=None)


class SheetView:
    def __init__(self, sheet, title):
        self._sheet, self.title = sheet, title

    def __getattr__(self, name):
        return getattr(self._sheet, name)

    def __getitem__(self, key):
        return self._sheet[key]


class WorkbookView:
    def __init__(self, sheets):
        self.worksheets = list(sheets)
        self.sheetnames = [sheet.title for sheet in self.worksheets]

    def __getitem__(self, name):
        return next(sheet for sheet in self.worksheets if sheet.title == name)

    def close(self):
        pass  # The enclosing summary_scope owns the workbook.


def input_path(default):
    active = ACTIVE_SUMMARY.get()
    return active["path"] if active else default


def open_input(path, **kwargs):
    active = ACTIVE_SUMMARY.get()
    if active and Path(path) == active["path"]:
        return active["inputs"]
    return load_workbook(path, **kwargs)


def table_records(workbook, name):
    """Read typed public cells, never a serialized dashboard or hidden payload."""
    if name not in workbook.sheetnames:
        return []
    rows = workbook[name].iter_rows(values_only=True)
    headers = [str(value or "").strip() for value in next(rows, ())]
    return [dict(zip(headers, values)) for values in rows if any(value is not None for value in values)]


def visible_target_names(workbook):
    return list(dict.fromkeys(
        str(row["订单分析代际名"]) for row in table_records(workbook, MASTER_SHEET)
        if row.get("订单来源文件") and row.get("订单分析代际名")
    ))


ORDER_FIELDS = {"gross": "大定", "net": "留存大定", "small_to_big": "小转大", "direct": "直接大定", "lock": "交车锁单"}


def iso_day(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat() if isinstance(value, date) else str(value or "")


def date_cell(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return value


def source_text(value):
    if isinstance(value, dict):
        return "｜".join(str(value.get(key) or "") for key in ("file", "sheet"))
    return str(value or "")


SMALL_CURVE_SHEET = "小订参考曲线"
SMALL_TOTAL_SHEET = "小订来源总量"


def _source_parts(value):
    if isinstance(value, dict):
        return value.get("file") or "", value.get("sheet") or ""
    parts = str(value or "").split("｜", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def summary_quality(
    total_small: float,
    small_to_big: float,
    conversion: float,
    gross: float,
    direct: float,
    direct_share: float,
    cancel: float,
    cancel_rate: float,
    net: float,
    net_rate: float,
    lock: float,
    lock_rate: float,
    provided_fields: tuple[bool, ...] | None = None,
) -> tuple[float, float, list[str]]:
    fields = (total_small, small_to_big, conversion, gross, direct, direct_share, cancel, cancel_rate, net, net_rate, lock, lock_rate)
    presence = provided_fields or tuple(value not in (None, "") for value in fields)
    field_completeness = sum(bool(value) for value in presence) / len(fields)
    checks: list[tuple[bool, str]] = []
    if gross > 0 and (small_to_big > 0 or direct > 0):
        checks.append((abs(small_to_big + direct - gross) <= max(5.0, max(abs(small_to_big + direct), abs(gross)) * .002), "总小转大+总直接大定与总大定不一致"))
    for label, value in (("小订转化率", conversion), ("直接大定占比", direct_share), ("退订率", cancel_rate), ("留存大定率", net_rate), ("大定到锁单率", lock_rate)):
        if value not in (None, 0):
            checks.append((0 <= value <= 1, f"{label}超出0%～100%"))
    if gross > 0 and direct > 0 and direct_share > 0:
        checks.append((abs(direct_share - direct / gross) <= 0.02, "直接大定占比与数量不一致"))
    if gross > 0 and net > 0:
        checks.append((net <= gross * 1.02, "首销期留存大定高于总大定"))
    if gross > 0 and lock > 0:
        checks.append((lock <= gross * 1.02, "首销期锁单高于总大定"))
    issues = [message for passed, message in checks if not passed]
    consistency = sum(passed for passed, _ in checks) / len(checks) if checks else 0.0
    return field_completeness, consistency, issues


def public_forecast_tables(book, data, emit, weekly_rows=(), as_of_date=None, raw_profiles=None):
    """Store business inputs, not resolved stage choices or program state."""
    master = table_records(book, MASTER_SHEET)
    baseline = table_records(book, "预测基准总表")
    aliases = {"传播名": "历史传播名", "代际名": "订单分析代际名", "发布日": "首销开始", "首销截止": "首销结束"}
    for record in baseline:
        row = next((r for r in master if r.get("历史传播名") == record.get("传播名")), None)
        if row is None:
            row = {"历史传播名": record.get("传播名")}
            master.append(row)
        row.update({aliases.get(k, k): v for k, v in record.items() if v is not None})
    sources = table_records(book, INDEX_SHEET)
    history_file = next((r.get("原始文件") for r in sources if "历史" in str(r.get("来源类型"))), None)
    history_file = history_file or "小订及首销数据整理.xlsx"
    raw_profiles = list(raw_profiles if raw_profiles is not None else data.get("actuals", []))
    targets = {r["name"]: r for r in data.get("targets", [])}
    for target in targets.values():
        row = next((r for r in master if r.get("历史传播名") == target.get("history_model")
                    and r.get("订单分析代际名") == target["name"]), None)
        row = row if row is not None else next((r for r in master if r.get("订单分析代际名") == target["name"]), None)
        dates = {"首销开始": target.get("launch_date"), "首销结束": target.get("end_date"),
                 "小订开始": target.get("small_start_date"), "小订结束": target.get("small_end_date")}
        if row is None:
            row = {"历史传播名": target.get("history_model"), "订单分析代际名": target["name"]}
            master.append(row)
        elif any(row.get(k) is not None and iso_day(row[k]) != iso_day(v) for k, v in dates.items()):
            row = {k: row.get(k) for k in ("订单分析代际名", "品牌", "产品档位", "能源类型", "发布类型", "发布时段")}
            master.append(row)
        row.update({k: date_cell(v) for k, v in dates.items()})
        row["首销天数"] = target.get("days")
        raw = next((r for r in raw_profiles if r["model"] == target["name"]), {})
        files = [_source_parts(raw.get(k))[0] for k in ("day_source", "hour_source", "small_hour_source", "cancel_source")]
        files += [_source_parts(v)[0] for v in raw.get("small_daily_sources", {}).values()]
        files += [r.get("source_file") for r in data.get("steady_history", []) if r["model"] == target["name"]]
        row["订单来源文件"] = "、".join(dict.fromkeys(f for f in files if f)) or history_file
    master_headers = ["历史传播名", "订单分析代际名", "原始表简称/别名", "品牌", "产品档位", "能源类型",
        "发布类型", "发布时段", "小订开始", "小订结束", "首销开始", "首销结束", "首销天数",
        "总小订", "总小转大", "小订转化率", "总大定", "总直接大定", "直接大定占比",
        "总退订", "退订率", "首销期留存大定", "留存大定率", "首销期锁单", "大定到锁单率", "字段完整度", "订单来源文件"]
    emit(MASTER_SHEET, master_headers, [[r.get(k) for k in master_headers] for r in master],
         {k for k in master_headers if k.endswith("率") or "占比" in k or k == "字段完整度"})

    rows = []
    def add(model, historical, day, stage, kind, source, values):
        filename, sheet = _source_parts(source)
        rows.append({"订单分析代际名": model, "历史传播名": historical, "日期": date_cell(day.get("date")),
                     "订单阶段": stage, "生命周期": day.get("day"), **values,
                     "来源类型": kind, "来源文件": filename, "来源Sheet": sheet})
    totals = []
    for raw in raw_profiles:
        model, target = raw["model"], targets.get(raw["model"], {})
        for day in raw.get("days", []):
            stage = "平销" if day.get("date") and target.get("end_date") and day["date"] > target["end_date"] else "首销"
            add(model, target.get("history_model"), day, stage, "首销订单", raw.get("day_source"),
                {c: day.get(k) for k, c in ORDER_FIELDS.items()})
        for day in raw.get("small_daily_days", []):
            add(model, target.get("history_model"), day, "小订", "逐日小订", raw.get("small_daily_sources", {}).get(day.get("date")),
                {"小订数量": day.get("orders")})
        for kind, prefix, source_key in (("首销订单", "launch", "day_source"), ("小订退订", "cancel", "cancel_source")):
            value = raw.get(prefix + "_total_small")
            valid = raw.get(prefix + "_total_small_valid", value is not None and value > 0)
            dates = [d.get("date") for d in raw.get("cancel_days" if prefix == "cancel" else "days", []) if d.get("date")]
            filename, sheet = _source_parts(raw.get(source_key))
            if value is not None or dates or filename:
                basis = "退订进度反推" if prefix == "cancel" else "首销累计进度反推" if raw.get("launch_total_small_estimated") else "原表总量"
                totals.append([model, kind, value if valid else None, basis, filename, sheet,
                               date_cell(min(dates)) if dates else None, date_cell(max(dates)) if dates else None])
        # Preserve genuine intraday cumulative components in the daily business table;
        # the source type and timestamp prevent treating these as completed-day totals.
        for day in raw.get("hourly_days", []):
            stamp = day.get("date")
            if stamp:
                stamp += f"T{int(day.get('last_hour', 0)):02d}:00:00"
            if any(day.get(k) is not None for k in ("small_to_big", "direct", "lock")):
                add(model, target.get("history_model"), {"date": stamp}, "首销", "首销分时累计", raw.get("hour_source"),
                    {ORDER_FIELDS[k]: day.get(k) for k in ("small_to_big", "direct", "lock")})
    for item in data.get("history", []):
        for index, value in enumerate(item.get("daily_orders", [])):
            start = item.get("launch_date")
            day = {"day": f"D{index + 1}", "date": (date.fromisoformat(start) + timedelta(days=index)).isoformat() if start else None}
            add(item.get("generation") or item["model"], item["model"], day, "首销", "历史首销",
                {"file": history_file, "sheet": "总大定当日数量"}, {"大定": value})
    small_records = []
    max_curve = max((len(r.get("standard_progress", [])) for r in data.get("small_order_history", [])), default=0)
    for item in data.get("small_order_history", []):
        if item.get("daily_actual"):
            for i, value in enumerate(item.get("daily_orders", [])):
                dates = item.get("dates", [])
                add(item.get("generation") or item["model"], item["model"],
                    {"day": f"D{i+1}", "date": dates[i] if i < len(dates) else None}, "小订", "历史小订",
                    {"file": history_file, "sheet": item.get("source_sheet")}, {"小订数量": value})
        curve = item.get("standard_progress", [])
        small_records.append([item["model"], item.get("generation"), date_cell(item.get("small_start_date")),
            date_cell(item.get("small_end_date")), item.get("days"), item.get("total") if item.get("total_complete") or item.get("daily_actual") is False else None,
            item.get("total_source"), item.get("leads"), item.get("heat"), item.get("source_model") or item["model"],
            history_file, item.get("source_sheet"), date_cell(next(iter(item.get("dates") or []), None)),
            *curve, *([None] * (max_curve-len(curve)))])
    for item in data.get("steady_history", []):
        for day in item.get("daily", []):
            add(item["model"], None, day, "平销", "平销锁单",
                {"file": item.get("source_file"), "sheet": "、".join(item.get("daily_source_sheets", []))}, {"交车锁单": day.get("lock")})
    headers = ["订单分析代际名", "历史传播名", "日期", "订单阶段", "生命周期", "小订数量",
               *ORDER_FIELDS.values(), "来源类型", "来源文件", "来源Sheet"]
    # Exact duplicate source records are not duplicated or summed.
    unique = {tuple(row.get(k) for k in headers): row for row in rows}
    emit(DAILY_SHEET, headers, [[r.get(k) for k in headers] for r in sorted(unique.values(),
         key=lambda r: (r.get("订单分析代际名") or "", str(r.get("日期") or ""), r["来源类型"], str(r.get("生命周期") or "")))])
    for sheet, key, field, label, source_key in (
        (SMALL_HOURLY_SHEET, "small_hourly_days", "orders", "小时小订", "small_hour_source"),
        (LAUNCH_HOURLY_SHEET, "hourly_days", "gross", "小时大定", "hour_source")):
        records = [[raw["model"], date_cell(day.get("date")), hour.get("hour"), hour.get(field),
                    _source_parts(raw.get(source_key))[0]]
                   for raw in raw_profiles for day in raw.get(key, []) for hour in day.get("hours", [])]
        emit(sheet, ["订单分析代际名", "日期", "小时", label, "来源文件"], records)
    weekly = [list(r[:11]) for r in weekly_rows]
    for item in data.get("steady_history", []):
        for week in item.get("weeks", []):
            match = next((r for r in weekly if r[0] == item["model"] and r[1] == week["period"] and r[2] == "平销"), None)
            if match is None:
                weekly.append([item["model"], week["period"], "平销", date_cell(week["start_date"]), date_cell(week["end_date"]),
                    None, None, week.get("lock"), None, None, source_text({"file": item.get("source_file"), "sheet": item.get("source_sheet")})])
            else:
                match[7] = week.get("lock")
                match[10] = source_text({"file": item.get("source_file"), "sheet": item.get("source_sheet")})
    emit(WEEKLY_SHEET, ["订单分析代际名", "周期", "订单阶段", "统计开始", "统计结束", "大定", "留存大定", "交车锁单",
         "大定来源", "留存大定来源", "锁单来源"], sorted(weekly, key=lambda r: (r[0], iso_day(r[3]), r[2])))
    emit(SMALL_CURVE_SHEET, ["历史传播名", "订单分析代际名", "小订开始", "小订结束", "小订天数", "总小订", "总量来源",
         "线索数", "热度", "原始名称", "来源文件", "来源Sheet", "首条数据日期", *[f"D{i+1}" for i in range(max_curve)]],
         small_records, {f"D{i+1}" for i in range(max_curve)})
    emit(SMALL_TOTAL_SHEET, ["订单分析代际名", "来源类型", "总小订", "总量口径", "来源文件", "来源Sheet", "数据开始", "数据结束"], totals)
    guide = [
        ["口径", "数量与空值", "单位：单；0是已知无销量，空白是未知。未来日期不视为真实完成日。", None, None],
        ["口径", "订单by天", "按来源保留数量；不同来源是候选值，不跨来源累加。首销分时累计是时间戳时点快照，不是日新增。", None, None],
        ["口径", "参考曲线", "小订参考曲线仅保存标准曲线和参考基准；真实小订累计完成度由by天和有效总小订计算。", None, None],
        ["口径", "小订", "小订选配比例分析by天 → 小订退订分析分时汇总 → 历史小订by天", None, None],
        ["口径", "首销前", "小订退订分析 → 整理表", None, None],
        ["口径", "首销中", "首销期订单节奏 → 整理表", None, None],
        ["口径", "首销结束及平销关联首销", "整理表 → 首销期订单节奏 → 小订退订分析", None, None],
        ["口径", "平销", "预测交车锁单。完整周按周起止和阶段日期判断；不足完整周不当作完整周参考。", None, None],
        ["口径", "分母来源", "小订来源总量保留各候选来源的有效总量和统计范围；阶段切换重新应用优先级。", None, None],
        ["口径", "字段完整度", "保留原始表字段填写比例用于参考评分；口径一致性和质量状态由汇总中的数量重新计算。", None, None],
        ["生成", "数据判定日期", (as_of_date or date.today()).isoformat(), None, None],
    ]
    for record in sources:
        guide.append(["来源", record.get("原始文件"), record.get("包含内容"),
                      record.get("文件数据开始日期"), record.get("文件数据结束日期")])
    if "汇总说明" in book.sheetnames:
        info = dict(book["汇总说明"].iter_rows(min_row=2, values_only=True))
        book.properties.identifier = info.get("刷新签名")
    emit(GUIDE_SHEET, ["类型", "项目", "内容", "数据开始", "数据结束"], guide)
    for name in ("汇总说明", "字段说明", INDEX_SHEET, "预测基准总表", "小订及退订逐日", "当前小订分时", "当前订单逐日", "当前首销分时", SNAPSHOT_SHEET):
        if name in book.sheetnames:
            del book[name]
    first = [GUIDE_SHEET, MASTER_SHEET, SMALL_HOURLY_SHEET, LAUNCH_HOURLY_SHEET, DAILY_SHEET, WEEKLY_SHEET]
    book._sheets = [book[name] for name in first] + [s for s in book.worksheets if s.title not in first]


def read_public_forecast(book, history, today=None):
    """Reconstruct raw candidates from public business cells; resolve stages later."""
    from core.model_identity import model_key
    from modules.sales_forecast import _read_model_mapping, _read_model_master, _master_record, _brand
    current = today or date.today()
    masters = table_records(book, MASTER_SHEET)
    days = table_records(book, DAILY_SHEET)
    mapping, model_master = _read_model_mapping(), _read_model_master()
    grouped = {}
    for row in days:
        grouped.setdefault((row.get("订单分析代际名"), row.get("来源类型")), []).append(row)
    def lifecycle(row):
        return int(str(row.get("生命周期") or "D0")[1:])
    for item in history:
        selected = sorted([r for r in days if r.get("来源类型") == "历史首销" and r.get("历史传播名") == item["model"]], key=lifecycle)
        item["daily_orders"] = [r.get("大定") for r in selected]
        item["hourly_curve"] = []

    profiles, windows = [], {}
    by_model = {}
    for row in masters:
        if not row.get("订单来源文件"):
            continue
        model = row["订单分析代际名"]
        if model in by_model:
            continue
        windows[model_key(model)] = {"generation": model, "history_model": row.get("历史传播名"),
            "launch_date": iso_day(row.get("首销开始")), "end_date": iso_day(row.get("首销结束")),
            "small_start_date": iso_day(row.get("小订开始")), "small_end_date": iso_day(row.get("小订结束")),
            "days": row.get("首销天数"), "small": row.get("总小订"), "source_sheet": MASTER_SHEET}
        profile = {"model": model, "launch_date": windows[model_key(model)]["launch_date"],
                   "days": [], "cancel_days": [], "hourly_days": [], "small_hourly_days": [],
                   "small_daily_days": [], "small_daily_sources": {}}
        for r in grouped.get((model, "首销订单"), []):
            profile["days"].append({"date": iso_day(r.get("日期")), "day": r.get("生命周期"),
                                    **{k: r.get(c) for k, c in ORDER_FIELDS.items()}})
            profile["day_source"] = {"file": r.get("来源文件"), "sheet": r.get("来源Sheet")}
        profile["days"].sort(key=lambda r: (r.get("date") or "", int(str(r.get("day") or "D0")[1:])))
        for r in grouped.get((model, "逐日小订"), []):
            d = iso_day(r.get("日期"))
            profile["small_daily_days"].append({"date": d, "orders": r.get("小订数量")})
            profile["small_daily_sources"][d] = {"file": r.get("来源文件"), "sheet": r.get("来源Sheet")}
        profiles.append(profile)
        by_model[model] = profile
    for row in table_records(book, SMALL_TOTAL_SHEET):
        profile = by_model.get(row.get("订单分析代际名"))
        if profile is None:
            continue
        prefix = "cancel" if row.get("来源类型") == "小订退订" else "launch"
        value = row.get("总小订")
        profile[prefix + "_total_small"] = value or 0
        profile[prefix + "_total_small_valid"] = isinstance(value, (int, float)) and value > 0
        profile[prefix + "_total_small_reason"] = row.get("总量口径")
        profile[prefix + "_total_small_estimated"] = row.get("总量口径") == "首销累计进度反推"
        profile["cancel_source" if prefix == "cancel" else "day_source"] = {"file": row.get("来源文件"), "sheet": row.get("来源Sheet")}
        if prefix == "cancel":
            start, end = iso_day(row.get("数据开始")), iso_day(row.get("数据结束"))
            profile["cancel_latest_date"] = end
            if start and end:
                span = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
                profile["cancel_days"] = [{"date": (date.fromisoformat(start) + timedelta(days=i)).isoformat()} for i in range(max(span, 0))]
    for sheet, key, field, label, source_key in (
        (SMALL_HOURLY_SHEET, "small_hourly_days", "orders", "小时小订", "small_hour_source"),
        (LAUNCH_HOURLY_SHEET, "hourly_days", "gross", "小时大定", "hour_source")):
        buckets = {}
        for row in table_records(book, sheet):
            model, d = row.get("订单分析代际名"), iso_day(row.get("日期"))
            profile = by_model.get(model)
            if profile is None:
                continue
            profile[source_key] = {"file": row.get("来源文件"), "sheet": sheet}
            bucket = buckets.setdefault((model, d), {"date": d, "last_hour": 0, field: 0, "hours": []})
            hour, value = int(row["小时"]), row.get(label)
            bucket["last_hour"] = max(bucket["last_hour"], hour)
            bucket["hours"].append({"hour": hour, field: value})
            if isinstance(value, (int, float)):
                bucket[field] += value
        for (model, d), bucket in sorted(buckets.items()):
            bucket["hours"].sort(key=lambda r: r["hour"])
            if key == "hourly_days":
                bucket.update(small_to_big=None, direct=None, lock=None)
                for row in grouped.get((model, "首销分时累计"), []):
                    if iso_day(row.get("日期")) == d:
                        bucket.update({k: row[c] for k, c in ORDER_FIELDS.items() if row.get(c) is not None})
            by_model[model][key].append(bucket)
    small = []
    for row in table_records(book, SMALL_CURVE_SHEET):
        name, generation = row.get("历史传播名"), row.get("订单分析代际名") or ""
        start, end = iso_day(row.get("小订开始")), iso_day(row.get("小订结束"))
        first_date = iso_day(row.get("首条数据日期"))
        selected = [r for r in grouped.get((generation or name, "历史小订"), [])
                    if r.get("历史传播名") == name and
                    (not first_date or iso_day(r.get("日期")) ==
                     (date.fromisoformat(first_date) + timedelta(days=lifecycle(r)-1)).isoformat())]
        selected.sort(key=lifecycle)
        daily = [r.get("小订数量") for r in selected]
        dates = [iso_day(r.get("日期")) for r in selected]
        curve = [v for k, v in row.items() if k.startswith("D") and k[1:].isdigit()]
        while curve and curve[-1] is None:
            curve.pop()
        final_total = row.get("总小订")
        complete = isinstance(final_total, (int, float)) and final_total > 0
        total = final_total if complete else sum(v for v in daily if v is not None)
        actual = row.get("来源Sheet") != "小订进度"
        cumulative, running, prefix_complete = [], 0, True
        for value in daily:
            prefix_complete = prefix_complete and value is not None
            if prefix_complete:
                running += value
            cumulative.append(min(running / max(total, 1), 1) if prefix_complete and complete else None)
        if not actual and curve and total > 0:
            terminal = curve[-1] or 0
            if terminal > 0:
                daily, assigned, previous = [], 0, 0
                for index, value in enumerate(curve):
                    progress = min(max(value / terminal, 0), 1)
                    count = max(int(round((progress-previous)*total)), 0) if index < len(curve)-1 else max(total-assigned, 0)
                    daily.append(count)
                    assigned += count
                    previous = progress
                dates = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(len(daily))] if start else []
        attrs = _master_record(model_master, name, generation) or {}
        item = {"model": name, "generation": generation, "mapped": model_key(row.get("原始名称") or name) in mapping,
            "brand": attrs.get("品牌") or _brand(name), "tier": attrs.get("产品档位") or "未维护",
            "energy": attrs.get("能源类型") or "未维护", "node": attrs.get("发布类型") or attrs.get("发布节点") or "未维护",
            "launch_period": attrs.get("发布时段") or "未维护", "small_start_date": start, "small_end_date": end,
            "days": row.get("小订天数") or max(len(daily), 1), "total": total, "total_complete": complete,
            "total_source": row.get("总量来源"), "leads": row.get("线索数") or 0, "heat": row.get("热度") or 0,
            "daily_orders": daily, "dates": dates, "small_progress": cumulative, "standard_progress": curve,
            "d1_share": (daily[0] or 0) / max(total, 1) if daily and complete else 0,
            "small_hourly_curve": [], "daily_actual": actual, "source_sheet": row.get("来源Sheet"),
            "source_model": row.get("原始名称"), "event_id": "|".join(("small", model_key(name),
                model_key(generation or name), start or "no-date", str(row.get("来源Sheet") or "no-sheet")))}
        if not actual:
            item.pop("total_complete", None)
            item["d1_share"] = min(curve[0] / curve[-1], 1) if curve and curve[-1] > 0 else 0
        small.append(item)
    steady = []
    week_records = table_records(book, WEEKLY_SHEET)
    for model, profile in by_model.items():
        window = windows[model_key(model)]
        end = window.get("end_date")
        start = (date.fromisoformat(end) + timedelta(days=1)).isoformat() if end else ""
        daily_rows = sorted(grouped.get((model, "平销锁单"), []), key=lambda r: iso_day(r.get("日期")))
        weeks = []
        for row in week_records:
            if row.get("订单分析代际名") != model or row.get("订单阶段") != "平销":
                continue
            # Order-mix lock totals remain visible, but are not lock-mix references.
            if "锁单选配比例" not in _source_parts(row.get("锁单来源"))[0]:
                continue
            a, b = iso_day(row.get("统计开始")), iso_day(row.get("统计结束"))
            if not a or not b or not start:
                continue
            first, last = date.fromisoformat(a), date.fromisoformat(b)
            if first.weekday() != 0 or (last-first).days != 6 or last >= current or a < start:
                continue
            if not isinstance(row.get("交车锁单"), (int, float)) or row["交车锁单"] < 0:
                continue
            weeks.append({"period": row["周期"], "start_date": a, "end_date": b, "lock": row["交车锁单"]})
        weeks.sort(key=lambda r: r["start_date"])
        if any((date.fromisoformat(b["start_date"])-date.fromisoformat(a["start_date"])).days != 7 for a, b in zip(weeks, weeks[1:])):
            weeks = []
        if not daily_rows and not weeks:
            continue
        for i, week in enumerate(weeks, 1):
            week["week"] = i
        attrs = _master_record(model_master, model) or {}
        filename = daily_rows[0].get("来源文件") if daily_rows else SUMMARY_NAME
        sheets = list(dict.fromkeys(r.get("来源Sheet") for r in daily_rows if r.get("来源Sheet")))
        steady.append({"model": model, "generation": model, "mapped": True,
            "brand": attrs.get("品牌") or _brand(model), "tier": attrs.get("产品档位") or "未维护",
            "energy": attrs.get("能源类型") or "未维护", "node": attrs.get("发布类型") or "未维护",
            "steady_start_date": start, "weeks": weeks,
            "daily": [{"date": iso_day(r["日期"]), "lock": r.get("交车锁单"), "complete": iso_day(r["日期"]) < current.isoformat()} for r in daily_rows],
            "source_file": filename, "source_sheet": WEEKLY_SHEET, "daily_source_sheets": sheets,
            "event_id": "|".join(("steady", model_key(model), str(filename))), "lock_rate": None, "launch_days": None})
    return profiles, windows, small, steady


@contextmanager
def summary_scope(path, workbook=None):
    path = Path(path)
    owns_workbook = workbook is None
    if owns_workbook:
        workbook = load_workbook(path, read_only=False, data_only=True)
    token = None
    try:
        if DAILY_SHEET in workbook.sheetnames and GUIDE_SHEET in workbook.sheetnames:
            active = {"path": path, "inputs": WorkbookView(workbook.worksheets),
                      "workbook": workbook, "visible": True}
            token = ACTIVE_SUMMARY.set(active)
            yield active
            return
        if SNAPSHOT_SHEET in workbook.sheetnames:
            raise ValueError("销量汇总仍为旧版缓存结构，请运行main重新生成可见数据表")
        if INDEX_SHEET not in workbook.sheetnames:
            raise ValueError(f"{path.name}缺少数据来源目录，请运行main重新生成")
        groups, inputs, source_ranges = {}, list(workbook.worksheets), {}
        headers = [cell.value for cell in workbook[INDEX_SHEET][1]]
        range_columns = ([headers.index(label) for label in ("文件数据开始日期", "文件数据结束日期")]
                         if all(label in headers for label in ("文件数据开始日期", "文件数据结束日期")) else [])
        seen = set()
        for record in workbook[INDEX_SHEET].iter_rows(min_row=2, values_only=True):
            kind, filename, original, stored, *_ = record
            if not stored:
                continue
            if stored not in workbook.sheetnames or (filename, original) in seen:
                raise ValueError(f"汇总目录重复或缺少Sheet：{filename}/{original}")
            seen.add((filename, original))
            view = SheetView(workbook[stored], original)
            if kind == "订单":
                groups.setdefault(filename, []).append(view)
                if range_columns:
                    try:
                        start, end = (date.fromisoformat(str(record[column])) for column in range_columns)
                        source_ranges[filename] = (start, end) if start <= end else None
                    except (TypeError, ValueError):
                        source_ranges[filename] = None
            elif kind in {"历史", "映射"}:
                inputs = [sheet for sheet in inputs if sheet.title != original]
                inputs.append(view)
        store = WorkbookStore(path.parent)
        store.items = [WorkbookItem(Path(name), WorkbookView(sheets)) for name, sheets in groups.items()]
        for item in store.items:
            if item.path.name in source_ranges:
                item._boundary_date_range = source_ranges[item.path.name]
        active = {"path": path, "inputs": WorkbookView(inputs), "store": store}
        token = ACTIVE_SUMMARY.set(active)
        yield active
    finally:
        if token is not None:
            ACTIVE_SUMMARY.reset(token)
        if owns_workbook:
            workbook.close()
