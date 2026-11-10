from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.annotations import annotation_scope, create_annotations_router


SUBJECTS = [
    {"id": "group", "name": "鸿蒙智行", "type": "group", "parent": None},
    {"id": "wenjie", "name": "问界", "type": "brand", "parent": "鸿蒙智行"},
    {"id": "zhijie", "name": "智界", "type": "brand", "parent": "group"},
    {"id": "m7", "name": "问界 M7 2025款", "type": "generation", "parent": "问界"},
    {"id": "m9", "name": "问界 M9 2025款", "type": "generation", "parent": "wenjie"},
    {"id": "r7", "name": "智界 R7 2025款", "type": "generation", "parent": "智界"},
]


class AnnotationTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.client = self.make_client()

    def make_client(self, **kwargs):
        app = FastAPI()
        app.include_router(create_annotations_router(self.path, lambda: SUBJECTS, **kwargs))
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def add(self, **changes):
        payload = {"date": "2026-11-10", "subject": "wenjie", "text": "权益调整"}
        payload.update(changes)
        response = self.client.post("/api/annotations", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_crud_persists_across_service_restart_and_audits_delete(self):
        first = self.add()
        restarted = self.make_client()
        self.assertEqual(restarted.get("/api/annotations").json()["entries"], [first])
        updated = restarted.put("/api/annotations/" + first["id"], json={
            "date": "2026-11-11", "subject": "group", "text": "集团权益更新", "version": 1,
        })
        self.assertEqual(updated.status_code, 200)
        second = updated.json()
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["created_at"], first["created_at"])
        self.assertGreater(second["updated_at"], first["updated_at"])
        self.assertEqual(restarted.delete("/api/annotations/" + first["id"], params={"version": 2}).status_code, 200)
        self.assertEqual(self.make_client().get("/api/annotations").json()["entries"], [])
        with closing(sqlite3.connect(self.path / "annotations.sqlite3")) as db:
            self.assertEqual(db.execute("SELECT action,version FROM annotation_audit ORDER BY seq").fetchall(),
                             [("create", 1), ("update", 2), ("delete", 2)])

    def test_stale_update_and_delete_do_not_overwrite_another_edit(self):
        first = self.add()
        path = "/api/annotations/" + first["id"]
        change = {"date": first["date"], "subject": "m7", "text": "新权益", "version": 1}
        self.assertEqual(self.client.put(path, json=change).status_code, 200)
        self.assertEqual(self.client.put(path, json={**change, "text": "旧页面修改"}).status_code, 409)
        self.assertEqual(self.client.delete(path, params={"version": 1}).status_code, 409)
        self.assertEqual(self.client.get("/api/annotations").json()["entries"][0]["text"], "新权益")

    def test_concurrent_edits_have_exactly_one_winner(self):
        first = self.add()
        path = "/api/annotations/" + first["id"]
        def update(label):
            return self.client.put(path, json={"date": first["date"], "subject": "m7", "text": label, "version": 1}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = list(pool.map(update, ["权益A", "权益B"]))
        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual(self.client.get("/api/annotations").json()["entries"][0]["version"], 2)

    def test_validation_keeps_database_unchanged(self):
        valid = {"date": "2026-11-10", "subject": "m7", "text": "权益"}
        for field, value in [("date", "2026-02-29"), ("date", "2026-1-01"),
                             ("subject", "missing"), ("text", " "), ("text", "a" * 81),
                             ("text", "注\n释"), ("text", 123), ("date", None)]:
            with self.subTest(field=field, value=value):
                response = self.client.post("/api/annotations", json={**valid, field: value})
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.post("/api/annotations", json={**valid, "author": "fake"}).status_code, 422)
        self.assertEqual(self.client.get("/api/annotations").json()["entries"], [])

    def test_valid_leap_day_and_eighty_character_text(self):
        entry = self.add(date="2024-02-29", subject="*", text="注" * 80)
        self.assertEqual(len(entry["text"]), 80)

    def test_untrusted_identity_headers_are_not_audited_as_users(self):
        response = self.client.post("/api/annotations", json={"date": "2026-11-10", "subject": "*", "text": "权益"},
                                    headers={"X-User": "admin", "X-Forwarded-User": "admin", "X-Forwarded-For": "1.2.3.4"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["created_by"], "connection:testclient")

    def test_cross_origin_and_browser_form_writes_are_rejected(self):
        entry = self.add()
        payload = {"date": entry["date"], "subject": entry["subject"], "text": "危险覆盖"}
        for origin in ["https://evil.example", "null", "http://testserver.evil.example", "https://testserver", "http://testserver/path"]:
            with self.subTest(origin=origin):
                self.assertEqual(self.client.post("/api/annotations", json=payload, headers={"Origin": origin}).status_code, 403)
                self.assertEqual(self.client.put("/api/annotations/" + entry["id"], json={**payload, "version": 1}, headers={"Origin": origin}).status_code, 403)
                self.assertEqual(self.client.delete("/api/annotations/" + entry["id"], params={"version": 1}, headers={"Origin": origin}).status_code, 403)
        self.assertEqual(self.client.post("/api/annotations", json=payload, headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.post("/api/annotations", data=payload).status_code, 415)
        self.assertEqual(self.client.get("/api/annotations").json()["entries"], [entry])

    def test_same_origin_default_port_and_explicit_proxy_origin(self):
        payload = {"date": "2026-11-10", "subject": "m9", "text": "权益调整"}
        self.assertEqual(self.client.post("/api/annotations", json=payload, headers={"Origin": "http://testserver:80"}).status_code, 201)
        proxy = self.make_client(allowed_origins=["https://plan.example"])
        self.assertEqual(proxy.post("/api/annotations", json=payload, headers={"Origin": "https://plan.example"}).status_code, 201)
        self.assertEqual(proxy.post("/api/annotations", json=payload, headers={"Origin": "https://plan.example.evil"}).status_code, 403)
        with self.assertRaises(ValueError):
            self.make_client(allowed_origins=["*"])

    def test_missing_entry_and_invalid_versions(self):
        entry = self.add()
        path = "/api/annotations/" + entry["id"]
        payload = {"date": entry["date"], "subject": entry["subject"], "text": entry["text"]}
        for version in [0, -1, True, "1"]:
            self.assertEqual(self.client.put(path, json={**payload, "version": version}).status_code, 422)
        self.assertEqual(self.client.delete(path).status_code, 422)
        self.assertEqual(self.client.delete("/api/annotations/missing", params={"version": 1}).status_code, 404)
        self.assertEqual(self.client.put("/api/annotations/missing", json={**payload, "version": 1}).status_code, 404)

    def test_read_is_not_cached_and_head_is_supported(self):
        response = self.client.get("/api/annotations")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.client.head("/api/annotations").status_code, 200)

    def test_group_brand_and_model_scope_are_separate(self):
        self.assertEqual(annotation_scope("m7", SUBJECTS), {"*", "group", "wenjie", "m7"})
        self.assertEqual(annotation_scope("m9", SUBJECTS), {"*", "group", "wenjie", "m9"})
        self.assertEqual(annotation_scope("r7", SUBJECTS), {"*", "group", "zhijie", "r7"})
        self.assertEqual(annotation_scope("wenjie", SUBJECTS), {"*", "group", "wenjie"})
        self.assertEqual(annotation_scope("group", SUBJECTS), {"*", "group"})
        self.assertEqual(annotation_scope("missing", SUBJECTS), {"*"})

    def test_missing_parent_still_inherits_group_and_cycles_terminate(self):
        subjects = [*SUBJECTS, {"id": "orphan", "name": "新车", "type": "generation", "parent": "未知品牌"},
                    {"id": "a", "name": "A", "parent": "b"}, {"id": "b", "name": "B", "parent": "a"}]
        self.assertEqual(annotation_scope("orphan", subjects), {"*", "group", "orphan"})
        self.assertEqual(annotation_scope("a", subjects), {"*", "group", "a", "b"})
