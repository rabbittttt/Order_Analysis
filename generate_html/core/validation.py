from __future__ import annotations

import math
import logging
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


_FORECAST_BATCH = ContextVar("forecast_diagnostic_batch", default=None)


class ForecastWarningBatch(logging.Filter):
    """Keep unique warning evidence, with bounded summaries and full debug detail."""

    def __init__(self):
        super().__init__()
        self.groups = {}

    def filter(self, record):
        if record.levelno != logging.WARNING:
            return True  # Exceptions and errors must remain immediately visible.
        message = record.getMessage()
        label = re.match(r"\[([^]]+)\]", message)
        reason = re.search(r"(?:原因|缺失字段)=([^|]+)", message)
        key = (record.name, label[1] if label else "", str(record.msg), re.sub(r"\d+", "#", reason[1].strip()) if reason else "")
        group = self.groups.setdefault(key, set())
        if message not in group:
            group.add(message)
            logging.getLogger(record.name).debug("[诊断明细] %s", message)
        return False

    def flush(self):
        logger = logging.getLogger(__name__)
        for messages in self.groups.values():
            examples = sorted(messages)
            if len(examples) == 1:
                logger.warning("%s", examples[0])
            else:
                label = re.match(r"\[([^]]+)\]", examples[0])
                logger.warning("[预测诊断汇总] 类别=%s | 共%d项（重复读取已去重） | 示例=%s | 全部明细使用 --debug 查看",
                               label[1] if label else "来源或字段校验", len(examples), "；".join(examples[:3]))
        self.groups.clear()


def flush_forecast_diagnostics():
    batch = _FORECAST_BATCH.get()
    if batch is not None:
        batch.flush()


@contextmanager
def forecast_diagnostics():
    """Batch only forecast warnings for one run; restore filters even on failure."""
    if _FORECAST_BATCH.get():
        yield _FORECAST_BATCH.get()
        return
    batch = ForecastWarningBatch()
    token = _FORECAST_BATCH.set(batch)
    loggers = [logging.getLogger(name) for name in ("modules.sales_forecast", "sales_forecast_refresh")]
    for logger in loggers:
        logger.addFilter(batch)
    try:
        yield batch
    finally:
        for logger in loggers:
            logger.removeFilter(batch)
        _FORECAST_BATCH.reset(token)
        batch.flush()


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    subjects = manifest.get("subjects", [])
    if not subjects:
        warnings.append("未识别到任何分析主体")
    subject_ids = {subject["id"] for subject in subjects}
    for key, dashboard in manifest.get("dashboards", {}).items():
        if dashboard.get("subject_id") not in subject_ids:
            warnings.append(f"看板主体不存在: {key}")
        seen = set()
        def invalid(value):
            if isinstance(value, str):
                return "NaN" in value or "undefined" in value
            if isinstance(value, float):
                return not math.isfinite(value)
            if isinstance(value, (dict, list)):
                if id(value) in seen:
                    return False
                seen.add(id(value))
                if isinstance(value, dict):
                    return any(invalid(k) or invalid(v) for k, v in value.items())
                return any(invalid(v) for v in value)
            return False
        if invalid(dashboard):
            warnings.append(f"看板包含无效值: {key}")
        for source in dashboard.get("sources", []):
            if not source.get("file") or not source.get("sheet"):
                warnings.append(f"来源信息不完整: {key}")
        for grain, view in dashboard.get("views", {}).items():
            for period, page in view.get("pages", {}).items():
                for index, panel in enumerate(page.get("sections", []), start=1):
                    source = panel.get("source") or {}
                    if not source.get("file") or not source.get("sheet"):
                        warnings.append(f"看板来源信息不完整: {key}/{grain}/{period}/第{index}块")
    return warnings
