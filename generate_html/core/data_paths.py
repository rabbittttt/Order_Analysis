"""Locate shared Excel inputs without mixing them with a project's old copies."""

from __future__ import annotations

import os
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = CODE_ROOT.parent if CODE_ROOT.name.lower() == "scripts" else CODE_ROOT


def shared_data_root(project_root: Path = PROJECT_ROOT) -> Path | None:
    """An explicit root is authoritative even if it has not been created yet."""
    configured = os.environ.get("SHARED_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    candidate = project_root.parent / "共享数据"
    return candidate if candidate.is_dir() else None


def orders_input_directory(project_root: Path = PROJECT_ROOT) -> Path:
    shared = shared_data_root(project_root)
    return shared / "订单汇总" if shared is not None else project_root / "output_file"


def forecast_reference_directory(project_root: Path = PROJECT_ROOT) -> Path:
    shared = shared_data_root(project_root)
    return shared / "订单汇总" if shared is not None else project_root / "input_file" / "销量预测输入文件"


def model_information_directory(project_root: Path = PROJECT_ROOT) -> Path:
    shared = shared_data_root(project_root)
    return shared / "车型信息" if shared is not None else project_root / "input_file" / "销量预测输入文件"
