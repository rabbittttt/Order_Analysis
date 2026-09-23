from __future__ import annotations

from typing import Protocol

from core.excel import WorkbookStore
from core.models import Dashboard, Subject


class DashboardModule(Protocol):
    id: str
    label: str

    def build(self, store: WorkbookStore, subject: Subject) -> Dashboard | None: ...
