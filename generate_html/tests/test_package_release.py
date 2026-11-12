"""A clean checkout can ship code before any business data has been generated."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase

from package_release import ROOT, package


class PackageReleaseTests(TestCase):
    def run_python(self, arguments, cwd):
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        result = subprocess.run([sys.executable, "-B", *arguments], cwd=cwd,
                                env=env, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return result

    def test_clean_source_build_and_template_update_need_no_runtime_or_dependencies(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "source"
            shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns("__pycache__", "tests"))
            # -S omits site-packages: packaging requires only Python's standard library.
            first = base / "v1"
            self.run_python(["-S", "package_release.py", "--output", str(first)], source)
            old_assets = {p.name for p in (first / "web/assets").iterdir()}
            css = source / "templates/dashboard.css"
            css.write_bytes(css.read_bytes() + b"\n/* release update fixture */\n")
            second = base / "v2"
            missing_runtime = base / "never-generated"
            self.run_python(["-S", "package_release.py", "--output", str(second),
                             "--runtime", str(missing_runtime)], source)
            self.assertFalse(missing_runtime.exists())
            html = (second / "web/index.html").read_text(encoding="utf-8")
            referenced = set(re.findall(r'assets/([a-f0-9]{64}\.(?:css|js|png))', html))
            self.assertEqual(len(referenced), 4)
            self.assertNotEqual(referenced, old_assets)
            for name in referenced:
                self.assertEqual(hashlib.sha256((second / "web/assets" / name).read_bytes()).hexdigest(),
                                 name.split(".")[0])
            built = json.loads((second / "web/web-build.json").read_text())
            for name, digest in built.items():
                self.assertEqual(digest, hashlib.sha256((second / "templates" / name).read_bytes()).hexdigest())
            for name in ("datasets", "current.json", "state", "output_file", "tests"):
                self.assertFalse(list(second.rglob(name)), name)
            self.assertNotIn("__DASHBOARD_", html)

    def test_packaged_service_serves_shell_and_assets_before_first_dataset(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            release = base / "release"
            package(release)
            # Import from the actual release in a separate interpreter, not the workspace.
            code = '''
import hashlib, json, re, sys
from pathlib import Path
from fastapi.testclient import TestClient
from core.server import create_app
root = Path.cwd()
external = Path(sys.argv[1])
before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in root.rglob('*') if p.is_file()}
app = create_app(external/'runtime', external/'state', web_dir=root/'web',
                 input_dir=external/'empty-input', check_seconds=300, stable_seconds=60)
with TestClient(app, base_url='http://localhost') as client:
    health = client.get('/health')
    assert health.status_code == 200, health.text
    assert health.json()['dataset_id'] is None
    page = client.get('/')
    assert page.status_code == 200
    for asset in set(re.findall(r'assets/[a-f0-9]{64}\\.(?:css|js|png)', page.text)):
        assert client.get('/'+asset).content == (root/'web'/asset).read_bytes()
    assert client.get('/api/catalog').status_code == 503
after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in root.rglob('*') if p.is_file()}
assert before == after, 'Runtime changed the immutable release'
'''
            self.run_python(["-c", code, str(base / "persistent")], release)

    def test_existing_version_is_not_overwritten(self):
        with TemporaryDirectory() as folder:
            destination = Path(folder) / "release"
            destination.mkdir()
            marker = destination / "keep.txt"
            marker.write_text("existing version")
            with self.assertRaises(FileExistsError):
                package(destination)
            self.assertEqual(marker.read_text(), "existing version")

    def test_destination_inside_source_is_rejected_before_writing(self):
        with self.assertRaisesRegex(ValueError, "源码目录之外"):
            package(ROOT / "core" / "release-not-created")
