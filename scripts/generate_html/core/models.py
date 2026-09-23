from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Subject:
    id: str
    name: str
    type: str
    parent: str | None = None
    modules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceRef:
    file: str
    sheet: str
    note: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Dashboard:
    module_id: str
    subject_id: str
    views: dict[str, Any]
    sources: list[SourceRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "subject_id": self.subject_id,
            "views": self.views,
            "sources": [source.to_dict() for source in self.sources],
        }
