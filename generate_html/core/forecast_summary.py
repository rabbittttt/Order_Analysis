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
DAILY_SHEET = "全周期订单by天"
SMALL_HOURLY_SHEET = "小订by时"
LAUNCH_HOURLY_SHEET = "首销by时"
WEEKLY_SHEET = "首销平销订单by周"
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
        if row.get("可选预测对象") is True and row.get("订单分析代际名")
    ))


STAGE_NAMES = {"before": "首销前", "active": "首销中", "ended": "首销后", "unknown": "日期未维护"}
ORDER_FIELDS = {"gross": "大定", "net": "留存大定", "small_to_big": "小转大", "direct": "直接大定", "lock": "交车锁单"}
SMALL_FIELDS = {
    "small_start_date": "小订开始", "small_end_date": "小订结束", "days": "小订天数",
    "total": "历史小订总数", "total_complete": "历史小订总数完整", "total_source": "历史小订总数来源",
    "leads": "小订线索数", "heat": "小订热度", "daily_actual": "小订历史为真实日",
    "source_sheet": "小订历史来源", "source_model": "小订原始名称", "event_id": "小订事件标识",
    "small_start_hour": "小订首日开始小时",
    "mapped": "小订参考已映射",
}


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


def stage_choices(profile):
    choices = dict(profile.get("stage_profiles") or {})
    stage = profile.get("stage") or "unknown"
    if stage not in choices and (not choices or profile.get("stage")):
        choices[stage] = profile
    return choices


def public_forecast_tables(book, data, emit, weekly_rows=(), as_of_date=None):
    """Materialize typed domain tables. No dashboard serialization is retained.

    Historical reference events and stage-specific choices remain explicit. Equal
    choices share a row; the applicability column is a selector, not an extra sale.
    """
    master = table_records(book, MASTER_SHEET)
    by_history = {row.get("历史传播名"): row for row in master}
    baseline = table_records(book, "预测基准总表")
    aliases = {"传播名": "历史传播名", "代际名": "订单分析代际名", "发布日": "首销开始", "首销截止": "首销结束"}
    for record in baseline:
        name = record.get("传播名")
        row = by_history.get(name)
        if row is None:
            row = {"历史传播名": name}
            master.append(row)
            by_history[name] = row
        for key, value in record.items():
            column = aliases.get(key, key)
            if value is not None:
                row[column] = value
        row["首销历史参考"] = True
    for profile in data.get("small_order_history", []):
        row = by_history.get(profile["model"])
        if row is None or (row.get("小订事件标识") and row["小订事件标识"] != profile.get("event_id")):
            row = {"历史传播名": profile["model"], "订单分析代际名": profile.get("generation")}
            master.append(row)
            by_history.setdefault(profile["model"], row)
        row.update({column: date_cell(profile.get(key)) if key.endswith("_date") else profile.get(key)
                    for key, column in SMALL_FIELDS.items()})
        for key, column in (("daily_orders", "小订数量记录天数"), ("dates", "小订日期记录天数"),
                            ("small_progress", "小订完成度记录天数"), ("standard_progress", "小订标准进度天数")):
            row[column] = len(profile.get(key) or [])
        for key, column in (("brand", "品牌"), ("tier", "产品档位"), ("energy", "能源类型"), ("node", "发布类型"), ("launch_period", "发布时段")):
            if not row.get(column):
                row[column] = profile.get(key)
    actuals = {profile["model"]: profile for profile in data.get("actuals", [])}
    for target in data.get("targets", []):
        row = next((r for r in master if r.get("订单分析代际名") == target["name"] and r.get("历史传播名") == target.get("history_model")), None)
        if row is None:
            row = next((r for r in master if r.get("订单分析代际名") == target["name"]), None)
        if row is None:
            row = {"历史传播名": target.get("history_model"), "订单分析代际名": target["name"]}
            master.append(row)
        row["可选预测对象"] = True
        date_fields = (("launch_date", "首销开始"), ("end_date", "首销结束"), ("small_start_date", "小订开始"), ("small_end_date", "小订结束"))
        independent = any(row.get(column) is not None and iso_day(row[column]) != iso_day(target.get(key)) for key, column in date_fields)
        row["当前窗口独立维护"] = independent
        for key, column in date_fields:
            row[("当前" if independent else "") + column] = date_cell(target.get(key))
        row[("当前" if independent else "") + "首销天数"] = target.get("days")
        row["当前总小订"] = actuals.get(target["name"], {}).get("total_small")
        for stage, profile in stage_choices(actuals.get(target["name"], {})).items():
            prefix = STAGE_NAMES[stage]
            row[prefix + "总小订"] = profile.get("total_small")
            row[prefix + "总小订来源"] = profile.get("total_small_source")
            row[prefix + "首选来源"] = profile.get("selected_source")
            row[prefix + "含分时"] = bool(profile.get("hourly_days"))
            row[prefix + "日明细来源"] = profile.get("field_sources", {}).get("首销日明细")
    for profile in data.get("steady_history", []):
        row = next((r for r in master if r.get("订单分析代际名") == profile["model"] and r.get("可选预测对象")), None)
        if row is None:
            row = next((r for r in master if r.get("订单分析代际名") == profile["model"]), None)
        if row is None:
            row = {"历史传播名": profile["model"], "订单分析代际名": profile["model"]}
            master.append(row)
        row.update({"平销历史参考": True, "平销开始": date_cell(profile.get("steady_start_date")),
                    "平销来源文件": profile.get("source_file"), "平销来源Sheet": profile.get("source_sheet"),
                    "平销事件标识": profile.get("event_id"), "平销大定到锁单率": profile.get("lock_rate"),
                    "平销参考首销天数": profile.get("launch_days")})
    # These duplicate the merged dates/source fields or are regenerated diagnostics.
    drop = {"首销阶段", "小订阶段", "取数来源", "数据问题"}
    headers = list(dict.fromkeys(k for row in master for k in row if k not in drop))
    emit(MASTER_SHEET, headers, [[row.get(k) for k in headers] for row in master],
         {k for k in headers if k.endswith("率") or "占比" in k or k in {"字段完整度", "口径一致性"}})

    rows = {}
    current_date = (as_of_date or date.today()).isoformat()
    def add_day(model, historical, event, day, stage, purpose, values, sources=None, **extra):
        row = {"订单分析代际名": model, "历史传播名": historical, "日期": date_cell(day.get("date")),
               "订单阶段": stage, "生命周期": day.get("day"), **values,
               **{column + "来源": (sources or {}).get(key) for key, column in ORDER_FIELDS.items()},
               "参考事件": event or None, **extra}
        day_value = iso_day(day.get("date"))
        row["数据状态"] = ("参考曲线（非真实日）" if extra.get("真实逐日") is False or not day_value else
                           "已结束日" if day_value < current_date else "当日快照（未结束）" if day_value == current_date else "未来日期（不作真实值）")
        # Same quantity/provenance is stored once with multiple uses, never added.
        key = tuple(sorted((k, v) for k, v in row.items() if v is not None))
        if key in rows:
            rows[key]["适用取数阶段"] += "、" + purpose
        else:
            rows[key] = {**row, "适用取数阶段": purpose}

    targets = {r["name"]: r for r in data.get("targets", [])}
    for profile in data.get("actuals", []):
        model = profile["model"]
        target = targets.get(model, {})
        variants = stage_choices(profile)
        for stage, candidate in variants.items():
            for day in candidate.get("days", []):
                order_stage = "平销" if day.get("date") and target.get("end_date") and day["date"] > target["end_date"] else "首销"
                add_day(model, target.get("history_model"), None, day, order_stage, STAGE_NAMES[stage],
                        {column: day.get(key) for key, column in ORDER_FIELDS.items()}, day.get("_field_sources"))
        for day in profile.get("small_daily_days", []):
            start = target.get("small_start_date")
            lifecycle = (date.fromisoformat(day["date"]) - date.fromisoformat(start)).days + 1 if start and day.get("date") else None
            add_day(model, target.get("history_model"), None, {**day, "day": f"D{lifecycle}" if lifecycle else None}, "小订", "当前小订",
                    {"小订数量": day.get("orders")}, 小订来源=source_text(profile.get("small_daily_sources", {}).get(day.get("date"))))
    for profile in data.get("history", []):
        for index, value in enumerate(profile.get("daily_orders", [])):
            start = profile.get("launch_date")
            day = {"day": f"D{index + 1}", "date": (date.fromisoformat(start) + timedelta(days=index)).isoformat() if start else None}
            add_day(profile.get("generation") or profile["model"], profile["model"], None, day, "首销", "首销历史参考", {"大定": value}, {"gross": "history"})
    for profile in data.get("small_order_history", []):
        count = max(len(profile.get(k, [])) for k in ("daily_orders", "small_progress", "standard_progress", "dates"))
        def at(key, index):
            values = profile.get(key) or []
            return values[index] if index < len(values) else None
        for index in range(count):
            add_day(profile.get("generation") or profile["model"], profile["model"], profile.get("event_id"),
                    {"day": f"D{index + 1}", "date": at("dates", index)}, "小订", "小订历史参考",
                    {"小订数量": at("daily_orders", index)},
                    小订参考累计完成度=at("small_progress", index), 小订标准进度=at("standard_progress", index),
                    小订来源=profile.get("source_sheet"), 真实逐日=profile.get("daily_actual"))
    for profile in data.get("steady_history", []):
        for day in profile.get("daily", []):
            add_day(profile["model"], None, None, day, "平销", "平销真实日", {"交车锁单": day.get("lock")},
                    {"lock": source_text({"file": profile.get("source_file"), "sheet": "、".join(profile.get("daily_source_sheets", []))})},
                    已结束日=day.get("complete"))
    # A reference curve may use exactly the same real quantity. Share that cell
    # when the event/date/quantity agree, retaining its reference-only metadata.
    visible_rows, same_day = [], {}
    for row in rows.values():
        key = (row.get("订单分析代际名"), row.get("历史传播名"), row.get("日期"), row.get("订单阶段"))
        purpose = row["适用取数阶段"]
        is_reference = purpose in {"小订历史参考", "首销历史参考"}
        quantity = "小订数量" if purpose == "小订历史参考" else "大定"
        match = next((candidate for candidate in same_day.get(key, [])
                      if is_reference and row.get("日期") is not None and row.get("真实逐日") is not False
                      and "历史参考" not in candidate["适用取数阶段"]
                      and candidate.get(quantity) == row.get(quantity)
                      and candidate.get("生命周期") == row.get("生命周期")), None)
        if match is not None:
            match["适用取数阶段"] += "、" + purpose
            for column in ("参考事件", "小订参考累计完成度", "小订标准进度", "真实逐日"):
                if row.get(column) is not None:
                    match[column] = row[column]
        else:
            visible_rows.append(row)
            same_day.setdefault(key, []).append(row)
    headers = ["订单分析代际名", "历史传播名", "日期", "订单阶段", "生命周期", "小订数量", *ORDER_FIELDS.values(),
               "适用取数阶段", "小订来源", *[c + "来源" for c in ORDER_FIELDS.values()],
               "小订参考累计完成度", "小订标准进度", "真实逐日", "已结束日", "参考事件", "数据状态"]
    emit(DAILY_SHEET, headers, [[row.get(k) for k in headers] for row in sorted(visible_rows, key=lambda r: (r["订单分析代际名"] or "", iso_day(r["日期"]) or "9999-12-31", r["订单阶段"], int(str(r.get("生命周期") or "D0")[1:]), r["适用取数阶段"]))], {"小订参考累计完成度", "小订标准进度"})

    for sheet, daily_key, quantity, quantity_label, references, curve_key in (
        (SMALL_HOURLY_SHEET, "small_hourly_days", "orders", "小时小订", data.get("small_order_history", []), "small_hourly_curve"),
        (LAUNCH_HOURLY_SHEET, "hourly_days", "gross", "小时大定", data.get("history", []), "hourly_curve"),
    ):
        records = []
        for profile in data.get("actuals", []):
            for day in profile.get(daily_key, []):
                hours = day.get("hours", [])
                for index, hour in enumerate(hours):
                    last = index == len(hours) - 1
                    records.append([profile["model"], None, date_cell(day.get("date")), hour.get("hour"), hour.get(quantity), None, "真实分时", None,
                                    *[day.get(key) if last else None for key in ("small_to_big", "direct", "lock")]])
        for profile in references:
            for hour, value in enumerate(profile.get(curve_key, [])):
                records.append([profile.get("generation") or profile["model"], profile["model"], date_cell(profile.get("small_start_date" if sheet == SMALL_HOURLY_SHEET else "launch_date")), hour, None, value, "历史参考", profile.get("event_id"), None, None, None])
        emit(sheet, ["订单分析代际名", "历史传播名", "日期", "小时", quantity_label, "参考累计占比", "用途", "参考事件", "截至末小时小转大", "截至末小时直接大定", "截至末小时交车锁单"], records, {"参考累计占比"})
    weekly = list(weekly_rows)
    # Weekly source values remain authoritative for complete steady reference weeks.
    for profile in data.get("steady_history", []):
        for week in profile.get("weeks", []):
            match = next((r for r in weekly if r[0] == profile["model"] and r[1] == week["period"] and r[2] == "平销"), None)
            if match is None:
                match = [profile["model"], week["period"], "平销", date_cell(week["start_date"]), date_cell(week["end_date"]), None, None, week.get("lock"), None, None, source_text({"file": profile.get("source_file"), "sheet": profile.get("source_sheet")}), True]
                weekly.append(match)
            else:
                match[7], match[11] = week.get("lock"), True
    emit(WEEKLY_SHEET, ["订单分析代际名", "周期", "订单阶段", "统计开始", "统计结束", "大定", "留存大定", "交车锁单", "大定来源", "留存大定来源", "锁单来源", "平销完整周参考"], sorted(weekly, key=lambda r: (r[0], iso_day(r[3]), r[2])))

    guide = [["口径", "数量单位", "单；空白表示缺失，0表示实际为零", None, None],
             ["口径", "by天用途", "同一日期的不同阶段取数结果通过适用取数阶段区分；只选择一种用途，不跨用途累加", None, None],
             ["口径", "小订优先级", "小订选配比例分析by天 → 小订退订分析分时汇总 → 历史小订by天", None, None],
             ["口径", "首销前", "小订退订分析 → 整理表", None, None],
             ["口径", "首销中", "首销期订单节奏 → 整理表", None, None],
             ["口径", "首销结束及平销关联首销", "整理表 → 首销期订单节奏 → 小订退订分析", None, None],
             ["口径", "平销预测", "真实锁单优先锁单选配比例分析；大定和留存大定仅汇总，不改变平销预测指标", None, None],
             ["口径", "边界周", "先按实际文件日期合并衔接片段；跨首销/平销周按by天拆分，日数据不足时留空，不将整周重复计入", None, None]]
    for record in table_records(book, INDEX_SHEET):
        guide.append(["来源", record.get("原始文件"), record.get("包含内容"), record.get("文件数据开始日期"), record.get("文件数据结束日期")])
    if "汇总说明" in book.sheetnames:
        info = dict(book["汇总说明"].iter_rows(min_row=2, values_only=True))
        book.properties.identifier = info.get("刷新签名")
    emit(GUIDE_SHEET, ["类型", "项目", "内容", "数据开始", "数据结束"], guide)
    for name in ("汇总说明", "字段说明", INDEX_SHEET, "预测基准总表", "小订及退订逐日", "当前小订分时", "当前订单逐日", "当前首销分时", SNAPSHOT_SHEET):
        if name in book.sheetnames:
            del book[name]
    first = [GUIDE_SHEET, MASTER_SHEET, DAILY_SHEET, SMALL_HOURLY_SHEET, LAUNCH_HOURLY_SHEET, WEEKLY_SHEET]
    book._sheets = [book[name] for name in first] + [sheet for sheet in book.worksheets if sheet.title not in first]


def read_public_forecast(book, history):
    """Rebuild forecast inputs from visible quantities, dates and reference curves."""
    from modules.sales_forecast import SOURCE_LABELS, STAGE_SOURCE_PRIORITIES
    from core.model_identity import model_key
    masters = table_records(book, MASTER_SHEET)
    days = table_records(book, DAILY_SHEET)
    by_use = {}
    for row in days:
        for use in str(row.get("适用取数阶段") or "").split("、"):
            by_use.setdefault((row.get("订单分析代际名"), use), []).append(row)
    history_by_name = {row["model"]: row for row in history}
    for item in history:
        rows = [r for r in days if r.get("历史传播名") == item["model"] and "首销历史参考" in str(r.get("适用取数阶段"))]
        rows.sort(key=lambda r: int(str(r.get("生命周期") or "D0")[1:]))
        item["daily_orders"] = [r.get("大定") for r in rows]
        item["hourly_curve"] = []
    hourly = {}
    small_history = []
    for row in masters:
        if not row.get("小订事件标识"):
            continue
        item = {key: iso_day(row.get(column)) if key.endswith("_date") else row.get(column) for key, column in SMALL_FIELDS.items()}
        item.update({"model": row.get("历史传播名"), "generation": row.get("订单分析代际名") or "",
                     "mapped": row.get("小订参考已映射") is True, "brand": row.get("品牌"), "tier": row.get("产品档位"),
                     "energy": row.get("能源类型"), "node": row.get("发布类型"), "launch_period": row.get("发布时段"), "small_hourly_curve": []})
        selected = [r for r in days if r.get("参考事件") == item["event_id"] and "小订历史参考" in str(r.get("适用取数阶段"))]
        selected.sort(key=lambda r: int(str(r.get("生命周期") or "D0")[1:]))
        item.update({"dates": [iso_day(r.get("日期")) for r in selected], "daily_orders": [r.get("小订数量") for r in selected],
                     "small_progress": [r.get("小订参考累计完成度") for r in selected], "standard_progress": [r.get("小订标准进度") for r in selected]})
        for key, column in (("daily_orders", "小订数量记录天数"), ("dates", "小订日期记录天数"),
                            ("small_progress", "小订完成度记录天数"), ("standard_progress", "小订标准进度天数")):
            item[key] = item[key][:int(row.get(column) or 0)]
        item["d1_share"] = (item["daily_orders"][0] or 0) / item["total"] if item.get("total") and item.get("total_complete") and item["daily_orders"] else 0
        small_history.append(item)
    small_by_event = {item["event_id"]: item for item in small_history}
    for sheet, quantity, label, key in ((SMALL_HOURLY_SHEET, "orders", "小时小订", "small_hourly_days"), (LAUNCH_HOURLY_SHEET, "gross", "小时大定", "hourly_days")):
        for row in table_records(book, sheet):
            if row.get("用途") == "历史参考":
                reference = small_by_event.get(row.get("参考事件")) if key == "small_hourly_days" else history_by_name.get(row.get("历史传播名"))
                if reference is not None:
                    curve = reference["small_hourly_curve" if key == "small_hourly_days" else "hourly_curve"]
                    hour = int(row["小时"])
                    while len(curve) <= hour:
                        curve.append(None)
                    curve[hour] = row.get("参考累计占比")
                continue
            group = hourly.setdefault((row["订单分析代际名"], key), {})
            day = iso_day(row.get("日期"))
            bucket = group.setdefault(day, {"date": day, "last_hour": 0, quantity: 0, "hours": []})
            bucket["last_hour"] = max(bucket["last_hour"], int(row["小时"]))
            value = row.get(label)
            bucket["hours"].append({"hour": int(row["小时"]), quantity: value})
            if isinstance(value, (int, float)):
                bucket[quantity] += value
            for field, column in (("small_to_big", "截至末小时小转大"), ("direct", "截至末小时直接大定"), ("lock", "截至末小时交车锁单")):
                if row.get(column) is not None:
                    bucket[field] = row[column]
    reference = {"file": SUMMARY_NAME, "sheet": DAILY_SHEET, "note": "可见订单数据"}
    profiles, windows, steady = [], {}, []
    week_records = table_records(book, WEEKLY_SHEET)
    for row in masters:
        model = row.get("订单分析代际名")
        if row.get("可选预测对象"):
            prefix = "当前" if row.get("当前窗口独立维护") else ""
            windows[model_key(model)] = {"generation": model, "history_model": row.get("历史传播名"),
                "launch_date": iso_day(row.get(prefix + "首销开始")), "end_date": iso_day(row.get(prefix + "首销结束")),
                "small_start_date": iso_day(row.get(prefix + "小订开始")), "small_end_date": iso_day(row.get(prefix + "小订结束")),
                "days": row.get(prefix + "首销天数"), "small": row.get("总小订"), "source_sheet": MASTER_SHEET}
            profile = {"model": model, "launch_date": iso_day(row.get(prefix + "首销开始")), "total_small": row.get("当前总小订"),
                       "stage_profiles": {}, "cancel_days": [], "day_source": reference,
                       "small_daily_days": [{"date": iso_day(r.get("日期")), "orders": r.get("小订数量")} for r in by_use.get((model, "当前小订"), [])]}
            for key in ("hourly_days", "small_hourly_days"):
                profile[key] = sorted(hourly.get((model, key), {}).values(), key=lambda r: r["date"])
                for bucket in profile[key]:
                    bucket["hours"].sort(key=lambda r: r["hour"])
            profile["hour_source"] = {"file": SUMMARY_NAME, "sheet": LAUNCH_HOURLY_SHEET}
            profile["small_hour_source"] = {"file": SUMMARY_NAME, "sheet": SMALL_HOURLY_SHEET}
            profile["small_daily_sources"] = {r["date"]: reference for r in profile["small_daily_days"]}
            for stage, prefix in STAGE_NAMES.items():
                if prefix + "首选来源" not in row or row.get(prefix + "首选来源") is None:
                    continue
                selected = row.get(prefix + "首选来源") or "missing"
                stage_days = [{"date": iso_day(r.get("日期")), "day": r.get("生命周期"),
                               **{k: r.get(c) for k, c in ORDER_FIELDS.items()},
                               "_field_sources": {k: r.get(c + "来源") for k, c in ORDER_FIELDS.items() if r.get(c + "来源")}}
                              for r in by_use.get((model, prefix), [])]
                total = row.get(prefix + "总小订")
                field_sources = {"首销日明细": row.get(prefix + "日明细来源") or SOURCE_LABELS.get(selected, "数据缺失"), "总小订": SOURCE_LABELS.get(row.get(prefix + "总小订来源"), "数据缺失"), "分时进度": "首销期订单节奏" if row.get(prefix + "含分时") else "数据缺失"}
                for field in ORDER_FIELDS:
                    owners = {r["_field_sources"][field] for r in stage_days if r["_field_sources"].get(field)}
                    source = next(iter(owners)) if len(owners) == 1 else "mixed" if owners else None
                    if source:
                        field_sources["首销日·" + field] = SOURCE_LABELS.get(source, source)
                profile["stage_profiles"][stage] = {"stage": stage, "priority": list(STAGE_SOURCE_PRIORITIES[stage]),
                    "days": stage_days, "hourly_days": profile["hourly_days"] if row.get(prefix + "含分时") else [],
                    "total_small": total, "total_small_source": row.get(prefix + "总小订来源"), "selected_source": selected,
                    "selected_source_label": SOURCE_LABELS.get(selected, "数据缺失"), "field_sources": field_sources,
                    "missing_fields": (["首销日真实进度"] if not stage_days and stage != "before" else []) + (["总小订"] if not total else []),
                    "data_missing": selected == "missing", "day_source": reference,
                    "source_latest_date": max((r["date"] for r in stage_days), default="")}
            profiles.append(profile)
        if row.get("平销历史参考"):
            weeks = [{"period": r["周期"], "start_date": iso_day(r["统计开始"]), "end_date": iso_day(r["统计结束"]), "lock": r.get("交车锁单")} for r in week_records if r["订单分析代际名"] == model and r.get("平销完整周参考") is True]
            weeks.sort(key=lambda r: r["start_date"])
            for index, week in enumerate(weeks, 1):
                week["week"] = index
            daily = [{"date": iso_day(r["日期"]), "lock": r.get("交车锁单"), "complete": r.get("已结束日")} for r in by_use.get((model, "平销真实日"), [])]
            steady.append({"model": model, "generation": model, "mapped": True, "brand": row.get("品牌"), "tier": row.get("产品档位"),
                "energy": row.get("能源类型"), "node": row.get("发布类型"), "steady_start_date": iso_day(row.get("平销开始")),
                "source_file": SUMMARY_NAME, "source_sheet": WEEKLY_SHEET, "daily_source_sheets": [DAILY_SHEET],
                "event_id": row.get("平销事件标识"), "lock_rate": row.get("平销大定到锁单率"), "launch_days": row.get("平销参考首销天数"),
                "weeks": weeks, "daily": daily})
    return profiles, windows, small_history, steady


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
