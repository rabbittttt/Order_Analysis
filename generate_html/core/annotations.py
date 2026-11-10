"""Shared trend annotations; SQLite lives outside versioned application files."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable, Iterable
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnnotationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    date: str
    subject: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=80)

    @field_validator("date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("事件日期须为 YYYY-MM-DD")
        date.fromisoformat(value)
        return value

    @field_validator("text")
    @classmethod
    def valid_text(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("批注内容不能为空或包含控制字符")
        return value


class AnnotationUpdate(AnnotationInput):
    version: int = Field(ge=1)


def annotation_scope(subject_id: str, subjects: Iterable[dict]) -> set[str]:
    """Resolve explicit parents (legacy names or IDs), never name prefixes."""
    subjects = list(subjects)
    by_id = {item["id"]: item for item in subjects}
    by_name = {item["name"]: item for item in subjects}
    current = by_id.get(subject_id)
    if not current:
        return {"*"}
    result = {"*", *(item["id"] for item in subjects if item.get("type") == "group")}
    visited = set()
    while current and current["id"] not in visited:
        visited.add(current["id"])
        result.add(current["id"])
        parent = current.get("parent")
        current = by_id.get(parent) or by_name.get(parent)
    return result


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            return None
        return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def create_annotations_router(
    state_dir: Path,
    get_subjects: Callable[[], list[dict]],
    *,
    allowed_origins: Iterable[str] = (),
) -> APIRouter:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "annotations.sqlite3"
    trusted_origins = set()
    for value in allowed_origins:
        normalized = _origin(value)
        if normalized is None:
            raise ValueError("allowed_origins must contain complete HTTP(S) origins")
        trusted_origins.add(normalized)

    @contextmanager
    def connection():
        db = sqlite3.connect(db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS annotations (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                subject TEXT NOT NULL,
                text TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT NOT NULL,
                updated_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS annotation_audit (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                annotation_id TEXT NOT NULL,
                action TEXT NOT NULL,
                version INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                actor TEXT NOT NULL,
                entry_json TEXT NOT NULL
            );
        """)

    def authorize_write(request: Request):
        # No client-supplied user/header is treated as a verified identity.
        # Deployment must enforce its department boundary outside this router.
        if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
            raise HTTPException(403, "禁止跨站修改批注")
        origin = request.headers.get("origin")
        if origin is not None:
            normalized = _origin(origin)
            local_origin = _origin(f"{request.url.scheme}://{request.url.netloc}")
            if normalized is None or normalized not in trusted_origins | {local_origin}:
                raise HTTPException(403, "禁止跨站修改批注")
        if request.method in ("POST", "PUT"):
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                raise HTTPException(415, "批注请求须使用 JSON")

    def validate_subject(value: str):
        if value != "*" and value not in {item["id"] for item in get_subjects()}:
            raise HTTPException(422, "适用范围不存在，请刷新页面")

    def now():
        return datetime.now(timezone.utc).isoformat(timespec="microseconds")

    def actor(request: Request):
        return "connection:" + (request.client.host if request.client else "unknown")

    def record(db, entry: dict, action: str, who: str, at: str):
        db.execute(
            "INSERT INTO annotation_audit(annotation_id,action,version,occurred_at,actor,entry_json) VALUES(?,?,?,?,?,?)",
            (entry["id"], action, entry["version"], at, who, json.dumps(entry, ensure_ascii=False)),
        )

    def existing(db, annotation_id: str, version: int):
        row = db.execute("SELECT * FROM annotations WHERE id=?", (annotation_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "批注已被删除")
        if row["version"] != version:
            raise HTTPException(409, "批注已被其他人修改，请刷新后重试")
        return dict(row)

    router = APIRouter()

    @router.api_route("/api/annotations", methods=["GET", "HEAD"])
    def list_annotations(response: Response):
        response.headers["Cache-Control"] = "no-store"
        with connection() as db:
            rows = db.execute("SELECT * FROM annotations ORDER BY date,created_at,id").fetchall()
            return {"entries": [dict(row) for row in rows]}

    @router.post("/api/annotations", status_code=201, dependencies=[Depends(authorize_write)])
    def add_annotation(payload: AnnotationInput, request: Request):
        validate_subject(payload.subject)
        at, who = now(), actor(request)
        entry = {"id": uuid4().hex, **payload.model_dump(), "version": 1,
                 "created_at": at, "updated_at": at, "created_by": who, "updated_by": who}
        with connection() as db:
            db.execute(
                "INSERT INTO annotations(id,date,subject,text,version,created_at,updated_at,created_by,updated_by) VALUES(:id,:date,:subject,:text,:version,:created_at,:updated_at,:created_by,:updated_by)",
                entry,
            )
            record(db, entry, "create", who, at)
        return entry

    @router.put("/api/annotations/{annotation_id}", dependencies=[Depends(authorize_write)])
    def update_annotation(annotation_id: str, payload: AnnotationUpdate, request: Request):
        validate_subject(payload.subject)
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            entry = existing(db, annotation_id, payload.version)
            at, who = now(), actor(request)
            entry.update(payload.model_dump())
            entry.update(version=payload.version + 1, updated_at=at, updated_by=who)
            db.execute("UPDATE annotations SET date=:date,subject=:subject,text=:text,version=:version,updated_at=:updated_at,updated_by=:updated_by WHERE id=:id", entry)
            record(db, entry, "update", who, at)
        return entry

    @router.delete("/api/annotations/{annotation_id}", dependencies=[Depends(authorize_write)])
    def delete_annotation(annotation_id: str, request: Request, version: int = Query(ge=1)):
        with connection() as db:
            db.execute("BEGIN IMMEDIATE")
            entry = existing(db, annotation_id, version)
            db.execute("DELETE FROM annotations WHERE id=?", (annotation_id,))
            record(db, entry, "delete", actor(request), now())
        return {"deleted": annotation_id}

    return router
