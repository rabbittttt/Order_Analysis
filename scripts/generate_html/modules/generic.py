from __future__ import annotations

import logging
from pathlib import Path

from core.components import kpi, section, table
from core.config import load_config
from core.excel import WorkbookStore, clean_text, compact_text, sheet_subject
from core.models import Dashboard, SourceRef, Subject


KNOWN_FILES = (
    ("SKU收敛度", "SKU收敛"),
    ("大定选配比例", "大定选配"),
    ("小订选配比例", "小订选配"),
    ("小订退订", "小订节奏"),
    ("订单7级转化", "订单7级转化"),
    ("选配金统计", "选配金"),
    ("锁单选配比例", "锁单选配"),
    ("首销期订单节奏", "首销节奏"),
)
LOGGER = logging.getLogger(__name__)


def _preview(sheet) -> tuple[dict, int]:
    rows, numeric_cells = [], 0
    for values in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 80), max_col=min(sheet.max_column, 24), values_only=True):
        row = [value.isoformat() if hasattr(value, "isoformat") else value for value in values]
        while row and row[-1] in (None, ""):
            row.pop()
        if not any(value not in (None, "") for value in row):
            continue
        numeric_cells += sum(isinstance(value, (int, float)) for value in row)
        rows.append(row)
    width = max((len(row) for row in rows), default=0)
    columns = [clean_text(value) or f"列{index + 1}" for index, value in enumerate((rows[0] if rows else []) + [None] * max(width - len(rows[0] if rows else []), 0))]
    body = [row + [None] * (width - len(row)) for row in rows[1:]]
    return table(columns, body), numeric_cells


class GenericModule:
    id = "generic"
    label = "导入分析"

    def __init__(self) -> None:
        self._dashboards: dict = {}
        config = load_config(Path(__file__).resolve().parents[1] / "config.json")
        self._labels: dict[str, str] = config.get("module_labels", {})
        self._chart_render_mode = config.get("chart_render_mode", "generated")

    def set_dashboards(self, dashboards: dict) -> None:
        """Receive the dashboards built so far; used to tell which boards consumed a sheet."""
        self._dashboards = dashboards

    def _consumers(self, subject: Subject, file: str, sheet_name: str) -> list[str]:
        prefix = f"{subject.id}|"
        consumers: set[str] = set()
        for key, board in self._dashboards.items():
            if not key.startswith(prefix):
                continue
            for source in board.get("sources", []):
                if source.get("file") == file and source.get("sheet") == sheet_name:
                    module_id = board.get("module_id", "")
                    consumers.add(self._labels.get(module_id, module_id))
        return sorted(consumers)

    def _count_numeric(self, sheet) -> int:
        count = 0
        for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 80), max_col=sheet.max_column):
            for cell in row:
                value = cell.value
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    count += 1
        return count

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None:
        routine, unmatched, sources = [], [], []
        for item in store.items:
            recognized_type = next((label for keyword, label in KNOWN_FILES if keyword in item.path.name), None)
            for sheet in item.workbook.worksheets:
                if compact_text(sheet_subject(sheet.title)) != compact_text(subject.name):
                    continue
                source = SourceRef(item.path.name, sheet.title, "标准结构识别" if recognized_type else "通用结构预览")
                sources.append(source)
                if recognized_type:
                    consumers = self._consumers(subject, item.path.name, sheet.title)
                    numeric = self._count_numeric(sheet)
                    row_count = max(sheet.max_row, 1)
                    col_count = max(sheet.max_column, 1)
                    if consumers:
                        status = "已进入看板"
                    elif "图表" in sheet.title:
                        mode_label = "读取原图" if self._chart_render_mode == "original" else "自行生成图表"
                        status = f"原始图表Sheet（当前配置为{mode_label}）"
                    elif numeric == 0:
                        status = "需核查：无数值数据"
                    elif row_count <= 2:
                        status = "需核查：疑似仅包含表头"
                    else:
                        status = "需核查：尚未被看板使用"
                    routine.append([
                        item.path.name, sheet.title, recognized_type,
                        "、".join(consumers) or "—",
                        f"{row_count}行 × {col_count}列", numeric, status,
                    ])
                    if status.startswith("需核查："):
                        LOGGER.warning(
                            "[数据诊断] 主体=%s | 识别模块=%s | 文件=%s | Sheet=%s | 状态=%s | 规模=%d行×%d列 | 数值单元格=%d | 处理=保留在导入分析中等待修正",
                            subject.name, recognized_type, item.path.name, sheet.title,
                            status.removeprefix("需核查："), row_count, col_count, numeric,
                        )
                    continue
                preview, numeric_cells = _preview(sheet)
                LOGGER.warning(
                    "[映射诊断] 主体=%s | 文件=%s | Sheet=%s | 状态=未识别到专属看板映射 | 规模=%d行×%d列 | 数值单元格=%d | 回退=导入分析通用预览",
                    subject.name, item.path.name, sheet.title, sheet.max_row, sheet.max_column, numeric_cells,
                )
                unmatched.append({
                    "file": item.path.name, "sheet": sheet.title, "rows": sheet.max_row,
                    "cols": sheet.max_column, "numeric": numeric_cells, "table": preview,
                    "source": source,
                })
        if not routine and not unmatched:
            return None

        abnormal = sum(1 for row in routine if str(row[-1]).startswith("需核查："))
        sections = [
            section("table", "待归类数据", table(
                ["文件", "Sheet", "规模", "处理方式"],
                [[item["file"], item["sheet"], f'{item["rows"]}行 × {item["cols"]}列', "通用表格预览"] for item in unmatched],
            ), "尚未配置专属业务映射，暂以通用表格呈现", source=unmatched[0]["source"] if unmatched else (sources[0] if sources else None)),
            section("table", "已识别数据", table(
                ["文件", "Sheet", "识别模块", "消费看板", "规模", "数值单元格", "状态"],
                routine,
            ), "已完成标准结构识别；标记为“需核查”的条目需要检查数据完整性或看板使用状态", source=sources[0] if sources else None),
        ]
        sections.extend(
            section("table", f'{item["file"]} · {item["sheet"]}', item["table"], f'{item["rows"]} 行 × {item["cols"]} 列', source=item["source"])
            for item in unmatched
        )
        page = {
            "kpis": [
                kpi("待归类Sheet", len(unmatched), "个", "通用结构预览", "orange"),
                kpi("已识别Sheet", len(routine), "个", "标准结构识别", "blue"),
                kpi("需核查Sheet", abnormal, "个", "数据完整性或使用状态待核查", "coral"),
                kpi("覆盖文件", len({source.file for source in sources}), "个", "当前分析主体", "green"),
                kpi("待配置结构", sum(item["numeric"] for item in unmatched), "个数值单元格", "预览范围", "purple"),
            ],
            "sections": sections,
        }
        views = {"week": {"periods": ["汇总"], "default_period": "汇总", "pages": {"汇总": page}}}
        return Dashboard(self.id, subject.id, views, sources)
