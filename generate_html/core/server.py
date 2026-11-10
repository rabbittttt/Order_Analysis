from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import re
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from core.annotations import create_annotations_router


DATASET_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
ROOT = Path(__file__).resolve().parents[1]
SERVICE_SOURCE_FILES = ("server.py", "core/server.py", "core/annotations.py", "requirements-server.txt")
# Keep the running process identity fixed even when a newer release is written.
SERVICE_FINGERPRINT = hashlib.sha256(
    b"".join((ROOT / name).read_bytes() for name in SERVICE_SOURCE_FILES)
).hexdigest()[:16]
CODE_ROOT = ROOT.parent
PROJECT_ROOT = CODE_ROOT.parent if CODE_ROOT.name.lower() == "scripts" else CODE_ROOT
DEFAULT_DATA_DIR = PROJECT_ROOT / "output_file" / "runtime"
DEFAULT_STATE_DIR = PROJECT_ROOT / "data" / "order_dashboard"
LEGACY_ENTRY = "鸿蒙智行订单分析汇总.html"
ASSET_SUFFIXES = {".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".json"}


def data_fingerprint(data_dir: Path) -> str:
    value = os.path.normcase(str(data_dir.resolve()))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def contained_file(root: Path, *parts: str) -> Path:
    """Resolve every path segment, including junctions, before exposing a file."""
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return target


def load_json(path: Path, compressed: bool = False) -> Any:
    try:
        opener = gzip.open if compressed else open
        with opener(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError, EOFError, zlib.error) as exc:
        raise HTTPException(503, "数据快照暂不可用") from exc


class SnapshotStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()

    def current_id(self) -> str:
        try:
            pointer = load_json(contained_file(self.data_dir, "current.json"))
        except HTTPException as exc:
            raise HTTPException(503, "尚无可用的数据快照") from exc
        dataset = pointer.get("dataset_id") if isinstance(pointer, dict) else None
        if not isinstance(dataset, str) or not re.fullmatch(DATASET_PATTERN, dataset):
            raise HTTPException(503, "数据快照标识无效")
        return dataset

    def dataset_file(self, dataset: str, *parts: str) -> Path:
        if not re.fullmatch(DATASET_PATTERN, dataset):
            raise HTTPException(400, "数据快照标识无效")
        return contained_file(self.data_dir, "datasets", dataset, *parts)

    @lru_cache(maxsize=4)
    def _catalog(self, dataset: str) -> dict[str, Any]:
        catalog = load_json(self.dataset_file(dataset, "catalog.json"))
        if not isinstance(catalog, dict):
            raise HTTPException(503, "数据目录格式无效")
        return {**catalog, "dataset_id": dataset}

    def catalog(self, dataset: str | None = None) -> dict[str, Any]:
        return self._catalog(dataset or self.current_id())

    def dashboard_file(self, dataset: str, subject: str, module: str) -> Path:
        subjects = self.catalog(dataset).get("subjects", [])
        selected = next((item for item in subjects if item.get("id") == subject), None)
        if selected is None or module not in selected.get("modules", []):
            raise HTTPException(404, "当前主体没有该看板")
        key = hashlib.sha256((subject + "|" + module).encode("utf-8")).hexdigest()
        return self.dataset_file(dataset, "boards", key + ".json.gz")

    def raw_file(self, dataset: str, file_index: int) -> dict[str, Any]:
        files = self.catalog(dataset).get("raw_files", [])
        if file_index < 0 or file_index >= len(files):
            raise HTTPException(404, "底表文件不存在")
        return files[file_index]

    def raw_sheet(self, dataset: str, file_index: int, sheet_index: int) -> dict[str, Any]:
        sheets = self.raw_file(dataset, file_index).get("sheets", [])
        if sheet_index < 0 or sheet_index >= len(sheets):
            raise HTTPException(404, "底表 Sheet 不存在")
        return sheets[sheet_index]

    @lru_cache(maxsize=4)
    def rows(self, dataset: str, file_index: int, sheet_index: int) -> list[list[Any]]:
        self.raw_sheet(dataset, file_index, sheet_index)
        path = self.dataset_file(dataset, "raw", f"{file_index}_{sheet_index}.json.gz")
        payload = load_json(path, compressed=True)
        rows = payload.get("rows") if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
            raise HTTPException(503, "底表数据格式无效")
        return rows


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def matching_rows(rows: list[list[Any]], query: str) -> Iterator[list[Any]]:
    keyword = query.strip().lower()
    for row in rows[1:]:
        if not keyword or any(keyword in cell_text(value).lower() for value in row):
            yield row


def safe_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", value).strip(". ") or "download"


def csv_chunks(rows: list[list[Any]], query: str) -> Iterator[bytes]:
    yield b"\xef\xbb\xbf"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    if rows:
        writer.writerow([cell_text(value) for value in rows[0]])
    for index, row in enumerate(matching_rows(rows, query), start=1):
        writer.writerow([cell_text(value) for value in row])
        if index % 200 == 0:
            yield buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate(0)
    if buffer.tell():
        yield buffer.getvalue().encode("utf-8")


def accepts_gzip(request: Request) -> bool:
    encodings = {}
    for part in request.headers.get("accept-encoding", "").lower().split(","):
        fields = [field.strip() for field in part.split(";")]
        quality = 1.0
        for field in fields[1:]:
            if field.startswith("q="):
                try:
                    quality = float(field[2:])
                except ValueError:
                    quality = 0.0
        encodings[fields[0]] = quality
    return encodings.get("gzip", encodings.get("*", 0.0)) > 0


def create_app(
    data_dir: Path | str | None = None,
    state_dir: Path | str | None = None,
    *,
    web_dir: Path | str | None = None,
    allowed_hosts: Sequence[str] | None = None,
    allowed_origins: Sequence[str] = (),
) -> FastAPI:
    store = SnapshotStore(Path(data_dir or DEFAULT_DATA_DIR))
    web_root = Path(web_dir).resolve() if web_dir else store.data_dir
    state_root = Path(state_dir or DEFAULT_STATE_DIR).resolve()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.snapshots = store
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(dict.fromkeys(("127.0.0.1", "localhost", *(allowed_hosts or ())))),
    )

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'self'")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.api_route("/health", methods=["GET", "HEAD"])
    @app.api_route("/api/health", methods=["GET", "HEAD"])
    def health():
        catalog = store.catalog()
        return {
            "status": "ok",
            "application": "order-dashboard",
            "dataset_id": catalog["dataset_id"],
            "data_fingerprint": data_fingerprint(store.data_dir),
            "service_fingerprint": SERVICE_FINGERPRINT,
        }

    @app.api_route("/api/catalog", methods=["GET", "HEAD"])
    def catalog():
        return JSONResponse(store.catalog(), headers={"Cache-Control": "no-store"})

    @app.api_route("/api/dashboard", methods=["GET", "HEAD"])
    def dashboard(
        request: Request,
        dataset: str = Query(pattern=DATASET_PATTERN),
        subject: str = Query(min_length=1, max_length=200),
        module: str = Query(min_length=1, max_length=100),
    ):
        path = store.dashboard_file(dataset, subject, module)
        headers = {
            "Cache-Control": "private, max-age=31536000, immutable",
            "Vary": "Accept-Encoding",
        }
        if accepts_gzip(request):
            headers["Content-Encoding"] = "gzip"
            return FileResponse(path, media_type="application/json", headers=headers)
        try:
            body = gzip.decompress(path.read_bytes())
        except (OSError, EOFError, zlib.error) as exc:
            raise HTTPException(503, "数据快照暂不可用") from exc
        return Response(body, media_type="application/json", headers=headers)

    @app.api_route("/api/chart", methods=["GET", "HEAD"])
    def chart(
        dataset: str = Query(pattern=DATASET_PATTERN),
        key: str = Query(min_length=1, max_length=1000),
    ):
        if key not in store.catalog(dataset).get("chart_assets", {}):
            raise HTTPException(404, "图表图片不存在")
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        for suffix, media_type in ((".png", "image/png"), (".jpg", "image/jpeg"), (".svg", "image/svg+xml")):
            try:
                path = store.dataset_file(dataset, "charts", digest + suffix)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            return FileResponse(
                path,
                media_type=media_type,
                headers={"Cache-Control": "private, max-age=31536000, immutable"},
            )
        raise HTTPException(404, "图表图片不存在")

    @app.api_route("/api/raw", methods=["GET", "HEAD"])
    def raw(
        dataset: str = Query(pattern=DATASET_PATTERN),
        file: int = Query(default=0, ge=0),
        sheet: int = Query(default=0, ge=0),
        q: str = Query(default="", max_length=500),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=500),
    ):
        rows = store.rows(dataset, file, sheet)
        page_rows, total = [], 0
        for row in matching_rows(rows, q):
            if offset <= total < offset + limit:
                page_rows.append(row)
            total += 1
        return {
            "rows": rows[:1] + page_rows,
            "total": total,
            "offset": offset,
            "limit": limit,
            "dataset_id": dataset,
        }

    @app.api_route("/api/export/csv", methods=["GET", "HEAD"])
    def export_csv(
        dataset: str = Query(pattern=DATASET_PATTERN),
        file: int = Query(default=0, ge=0),
        sheet: int = Query(default=0, ge=0),
        q: str = Query(default="", max_length=500),
    ):
        source = store.raw_file(dataset, file)
        selected_sheet = store.raw_sheet(dataset, file, sheet)
        name = Path(source.get("name") or "底表.xlsx").stem + "_" + (selected_sheet.get("name") or "Sheet") + ".csv"
        headers = {
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(safe_filename(name)),
            "Cache-Control": "no-store",
        }
        return StreamingResponse(
            csv_chunks(store.rows(dataset, file, sheet), q),
            media_type="text/csv; charset=utf-8",
            headers=headers,
        )

    @app.api_route("/api/workbook", methods=["GET", "HEAD"])
    def workbook(
        dataset: str = Query(pattern=DATASET_PATTERN),
        file: int = Query(default=0, ge=0),
    ):
        source = store.raw_file(dataset, file)
        return FileResponse(
            store.dataset_file(dataset, "workbooks", f"{file}.xlsx"),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=safe_filename(source.get("name") or f"底表{file}.xlsx"),
            headers={"Cache-Control": "no-store"},
        )

    @app.api_route("/", methods=["GET", "HEAD"])
    @app.api_route("/index.html", methods=["GET", "HEAD"])
    @app.api_route("/" + LEGACY_ENTRY, methods=["GET", "HEAD"])
    def index():
        return FileResponse(
            contained_file(web_root, "index.html"),
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @app.api_route("/assets/{asset_path:path}", methods=["GET", "HEAD"])
    def asset(asset_path: str):
        relative = Path(asset_path)
        if relative.suffix.lower() not in ASSET_SUFFIXES or any(part.startswith(".") for part in relative.parts):
            raise HTTPException(404, "资源不存在")
        return FileResponse(
            contained_file(web_root, "assets", asset_path),
            headers={"Cache-Control": "private, max-age=3600"},
        )

    app.include_router(create_annotations_router(
        state_root, lambda: store.catalog().get("subjects", []),
        allowed_origins=allowed_origins,
    ))
    return app
