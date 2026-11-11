"""One serialized, low-priority Excel refresh worker; HTTP never parses Excel."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_SECONDS = 300
STABLE_SECONDS = 60
EXCLUDED = {"鸿蒙智行销量数据汇总.xlsx"}
LOG = logging.getLogger(__name__)


class BuildLock:
    """OS-owned lock, released on crashes too; shared by CLI and automatic builds."""
    def __init__(self, runtime: Path, name: str = ".build.lock"):
        self.path = runtime / name
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        try:
            self.stream.seek(0, 2)
            if not self.stream.tell():
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise RuntimeError("已有订单数据更新任务正在运行") from exc
        return self

    def __exit__(self, *_):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def source_signature(source: Path) -> dict:
    if not source.is_dir():
        raise FileNotFoundError("订单 Excel 输入目录不存在")
    entries = []
    for path in sorted(source.iterdir(), key=lambda p: p.name):
        if path.suffix.lower() != ".xlsx" or path.name.startswith("~$") or path.name in EXCLUDED:
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError("Excel 输入必须是普通文件")
        stat = path.stat()
        entries.append([path.name, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns])
    if not any(row[0] != "小订及首销数据整理.xlsx" for row in entries):
        raise ValueError("输入目录没有订单汇总 Excel")
    marker = source / "orders.ready"
    marker_info = None
    if marker.exists():
        stat = marker.stat()
        marker_info = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
        if stat.st_mtime_ns < max(row[2] for row in entries):
            raise ValueError("等待本轮 Excel 更新完成标记 orders.ready")
    return {"directory": str(source.resolve()), "files": entries, "ready": marker_info}


def published_signature(runtime: Path) -> dict | None:
    try:
        dataset = json.loads((runtime / "current.json").read_text(encoding="utf-8"))["dataset_id"]
        # This is internal state, but still contain its lookup.
        catalog = (runtime / "datasets" / dataset / "catalog.json").resolve()
        if not catalog.is_relative_to((runtime / "datasets").resolve()):
            return None
        return json.loads(catalog.read_text(encoding="utf-8")).get("source_signature")
    except (OSError, ValueError, KeyError, TypeError):
        return None


class RefreshSchedule:
    """Pure timing policy: 5-minute idle polls, 1-minute debounce confirmations."""
    def __init__(self, check_seconds=CHECK_SECONDS, stable_seconds=STABLE_SECONDS):
        if check_seconds <= 0 or stable_seconds <= 0:
            raise ValueError("检查和稳定等待时间必须大于零")
        self.check_seconds = check_seconds
        self.stable_seconds = stable_seconds
        self.pending = None
        self.since = 0.0

    def observe(self, signature, published, now):
        if signature == published:
            self.pending = None
            return False, self.check_seconds
        if (isinstance(signature, dict) and signature.get("ready") is not None
                and isinstance(published, dict) and signature["ready"] == published.get("ready")):
            # Copy tools can preserve old Excel mtimes. An existing marker must
            # advance for a new batch, not merely be newer than those old mtimes.
            self.pending, self.since = signature, now
            return False, self.check_seconds
        if signature != self.pending:
            self.pending, self.since = signature, now
            return False, self.stable_seconds
        remaining = self.stable_seconds - (now - self.since)
        return remaining <= 0, max(remaining, 0)


def copy_stable_inputs(source: Path, destination: Path, expected: dict) -> None:
    if source_signature(source) != expected:
        raise RuntimeError("Excel 已变化，等待下一次稳定后更新")
    for name, size, *_ in expected["files"]:
        shutil.copy2(source / name, destination / name)
        if (destination / name).stat().st_size != size:
            raise RuntimeError("Excel 快照复制不完整")
    if source_signature(source) != expected:
        raise RuntimeError("复制期间 Excel 已变化，等待下一次稳定后更新")


def run_worker(source: Path, runtime: Path, expected: dict) -> None:
    # Lock before snapshotting. A second service/CLI must not calculate in parallel.
    with BuildLock(runtime):
        with tempfile.TemporaryDirectory(prefix=".order-input-", dir=runtime.parent) as folder:
            snapshot = Path(folder)
            copy_stable_inputs(source, snapshot, expected)
            os.environ["ORDER_DASHBOARD_INPUT"] = str(snapshot)
            # Import business modules only after the stage-identity source is pinned.
            import main as generator
            generator.configure_runtime(runtime.parent, False)
            try:
                generator.build(snapshot, runtime.parent / "鸿蒙智行订单分析汇总.html",
                                runtime_dir=runtime, source_signature=expected)
            finally:
                generator.cleanup_input_cache(runtime.parent)


class AutoSync:
    def __init__(self, source: Path, runtime: Path, check_seconds=CHECK_SECONDS, stable_seconds=STABLE_SECONDS):
        self.source, self.runtime = source.resolve(), runtime.resolve()
        self.schedule = RefreshSchedule(check_seconds, stable_seconds)
        self.stop_event = threading.Event()
        self.thread = None
        self.process = None
        self.phase = "waiting"
        self.error = None
        self.checked_at = None
        self.owner = None

    def status(self):
        return {"phase": self.phase, "error": self.error, "checked_at": self.checked_at,
                "check_seconds": self.schedule.check_seconds, "stable_seconds": self.schedule.stable_seconds}

    def start(self):
        # Refuse duplicate schedulers for the same runtime, even on different ports.
        self.owner = BuildLock(self.runtime, ".sync.lock")
        self.owner.__enter__()
        self.thread = threading.Thread(target=self._loop, name="order-auto-sync", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()  # loop interrupts and reaps its own child promptly
        if self.owner:
            self.owner.__exit__()

    def _terminate_worker(self):
        if self.process is None or self.process.poll() is not None:
            return
        if os.name == "nt":
            # A venv python.exe may be a redirector with a real Python child.
            # Stop only this worker's owned tree, never a port/global process list.
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        else:
            self.process.terminate()
        self.process.wait(timeout=10)

    def _build(self, signature):
        log_dir = self.runtime.parent / "log"
        log_dir.mkdir(parents=True, exist_ok=True)
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == "nt" else 0
        with (log_dir / "auto_sync.log").open("ab") as log:
            self.process = subprocess.Popen(
                [sys.executable, str(ROOT / "server.py"), "--sync-worker", "--input", str(self.source),
                 "--data-dir", str(self.runtime)], cwd=ROOT,
                stdin=subprocess.PIPE, stdout=log, stderr=log, creationflags=flags,
            )
            self.process.stdin.write(json.dumps(signature, ensure_ascii=False).encode("utf-8"))
            self.process.stdin.close()
            while self.process.poll() is None:
                if self.stop_event.wait(0.5):
                    self._terminate_worker()
                    return False
            result = self.process.returncode == 0
            self.process = None
            if not result:
                raise RuntimeError("更新失败，当前显示上次数据")
            if published_signature(self.runtime) != signature:
                raise RuntimeError("更新未发布，当前显示上次数据")
            return True

    def _loop(self):
        delay = 0
        while not self.stop_event.wait(delay):
            try:
                signature = source_signature(self.source)
                self.checked_at = time.time()
                build, delay = self.schedule.observe(signature, published_signature(self.runtime), time.monotonic())
                if not build:
                    self.phase = "waiting" if self.schedule.pending else "idle"
                    if not self.schedule.pending:
                        self.error = None
                    continue
                self.phase = "building"
                if self._build(signature):
                    self.phase, self.error = "idle", None
                    # Immediately observe again after a long build; changes coalesce.
                    delay = 0
            except Exception:
                self._terminate_worker()
                LOG.exception("订单自动同步失败；保留上一批可用数据")
                self.phase, self.error = "error", "更新失败，当前显示上次数据"
                self.schedule.pending = None
                delay = self.schedule.check_seconds
