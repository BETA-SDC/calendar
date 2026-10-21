import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from flask import Flask, session
from icalendar import Calendar

from server.api import register_calendar
from server.publisher import PublicationError, Publisher, RetryPublication, ROOT, run, snapshot
from server.store import Store
from server.worker import owner_access


class OnlineCalendarTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "source"
        source.mkdir()
        for name in ("public", "internal"):
            shutil.copytree(ROOT / name, source / name)
        self.git("init", "-b", "main", cwd=source)
        self.git("config", "user.name", "Test", cwd=source)
        self.git("config", "user.email", "test@example.invalid", cwd=source)
        self.git("add", ".", cwd=source)
        self.git("commit", "-m", "Fixtures", cwd=source)
        self.remote = self.root / "remote.git"
        self.git("clone", "--bare", str(source), str(self.remote))
        self.state = self.root / "state"
        self.store = Store(self.state / "calendar.sqlite3")
        self.actor = {"id": 1, "username": "editor"}
        self.admin = {"id": 2, "username": "admin"}
        self.store.grant(self.admin, self.admin, "admin")
        self.store.grant(self.admin, self.actor, "editor")
        self.publisher = Publisher(self.state, str(self.remote), self.store)
        self.publisher.sync()
        self.accounts = {1: self.actor, 2: self.admin, 3: {"id": 3, "username": "viewer"}}
        self.app = Flask(__name__)
        self.app.secret_key = "test-only"
        self.registration = Store(self.root / "accounts.sqlite3")
        with self.registration.connection() as db:
            db.executescript("""
                CREATE TABLE github_accounts(user_id INTEGER PRIMARY KEY);
                CREATE TABLE github_admin_grants(user_id INTEGER PRIMARY KEY, valid_until INTEGER);
                CREATE TABLE account_groups(id INTEGER PRIMARY KEY, external_key TEXT, archived INTEGER);
                CREATE TABLE group_members(user_id INTEGER, group_id INTEGER, source TEXT, valid_until INTEGER);
                INSERT INTO github_accounts VALUES(1),(2),(4);
                INSERT INTO account_groups VALUES(1,'github:org:BETA-SDC',0);
            """)
            until = int(time.time()) + 86400
            db.executemany("INSERT INTO github_admin_grants VALUES(?,?)", [(1, until), (2, until)])
            db.execute("INSERT INTO group_members VALUES(4,1,'github',?)", (until,))
        self.accounts[4] = {"id": 4, "username": "member"}
        self.app.extensions["registration_store"] = self.registration
        self.publisher.can_manage = lambda user_id: owner_access(self.registration.path, user_id)
        register_calendar(self.app, state=self.state,
                          current_user=lambda: self.accounts.get(session.get("user_id")),
                          csrf_token=lambda: session.setdefault("csrf_token", "csrf-test"))
        self.client = self.app.test_client()
        self.payload = {"title": "测试 / Test", "scope": "public",
                        "start": "2026-12-01T09:00", "end": "2026-12-01T10:00",
                        "description": "Test", "alarmMode": "set", "alarmMinutes": 10}

    def git(self, *args, cwd=None):
        return run(["git", *args], cwd=cwd)

    def login(self, user_id):
        with self.client.session_transaction() as current:
            current["user_id"] = user_id
            current["csrf_token"] = "csrf-test"

    def send(self, method, path, payload):
        return self.client.open("/api/calendar" + path, method=method, json=payload,
                                headers={"X-CSRF-Token": "csrf-test"})

    def data(self):
        return json.loads((self.state / "current/server-events.json").read_text())["events"]

    def publish(self, operation="add", uid="test@beta", payload=None):
        job_id = self.store.enqueue(self.actor, operation, uid, payload or self.payload)
        self.publisher.process(self.store.job(job_id))
        self.assertEqual(self.store.job(job_id)["state"], "succeeded")
        return job_id

    def test_public_capabilities_and_static_assets(self):
        response = self.client.get("/api/calendar/session").json
        self.assertFalse(response["canEdit"])
        self.assertIsNone(response["user"])
        for asset in ("", "calendar.js", "calendar-validation.js", "vendor/fullcalendar.js", "mark.png"):
            with self.client.get("/calendar/" + asset) as response:
                self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/calendar/server-events.json").status_code, 404)
        self.assertEqual(self.client.get("/calendar/../calendar.sqlite3").status_code, 404)
        with self.client.get("/calendar/") as response:
            self.assertIn("'unsafe-inline'", response.headers["Content-Security-Policy"])
            self.assertIn('class="calendar-local-nav"', response.get_data(as_text=True))

    def test_auth_and_csrf_are_server_side(self):
        self.assertEqual(self.send("POST", "/events", self.payload).status_code, 403)
        self.login(3)
        self.assertEqual(self.send("POST", "/events", self.payload).status_code, 403)
        self.login(1)
        self.assertEqual(self.client.post("/api/calendar/events", json=self.payload).status_code, 403)
        self.assertEqual(self.client.get("/api/calendar/roles").status_code, 404)
        self.assertEqual(self.send("POST", "/events", self.payload).status_code, 202)

    def test_guests_and_nonmembers_only_read_public_planned_events(self):
        response = self.client.get("/api/calendar/events")
        expected = [event for event in self.data()
                    if event["scope"] == "public" and event["status"] == "planned"]
        self.assertEqual({event["uid"] for event in response.json["events"]},
                         {event["uid"] for event in expected})
        self.assertTrue(all(not any(event["actions"].values()) for event in response.json["events"]))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        with self.client.get("/calendar/") as page:
            self.assertEqual(page.status_code, 200)
        self.assertTrue(all(event["scope"] == "public" and event["status"] == "planned"
                            for event in self.client.get("/calendar/events-data.json").json["events"]))
        self.assertEqual(self.client.get("/api/calendar/session").status_code, 200)
        for asset in ("calendar.css", "workspace.css", "calendar.js", "calendar-preferences.js",
                      "login.css", "login.js", "calendar-account.js", "mark.png"):
            with self.client.get("/calendar/" + asset) as response:
                self.assertEqual(response.status_code, 200)
        self.login(3)
        self.assertEqual(
            {event["uid"] for event in self.client.get("/api/calendar/events").json["events"]},
            {event["uid"] for event in expected},
        )
        self.assertEqual(
            {event["uid"] for event in self.client.get("/calendar/events-data.json").json["events"]},
            {event["uid"] for event in expected})
        subscription = self.client.get("/calendar/calendar-data.json").json
        self.assertTrue(subscription["feeds"])
        self.assertTrue(all(key.startswith("public@planned") for key in subscription["feeds"]))
        with self.client.get("/calendar/") as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.send("POST", "/events", self.payload).status_code, 403)

    def test_guest_cannot_bypass_filter_through_static_files_or_write(self):
        for asset in ("server-events.json", "revision.json", "all.ics",
                      "public.ics", "internal.ics", "tentative.ics"):
            self.assertEqual(self.client.get("/calendar/" + asset).status_code, 404, asset)
        for event in self.data():
            with self.client.get("/calendar/" + event["path"]) as response:
                allowed = event["scope"] == "public" and event["status"] == "planned"
                self.assertEqual(response.status_code, 200 if allowed else 404, event["path"])
        self.client.get("/api/calendar/session")
        self.assertEqual(self.send("POST", "/events", self.payload).status_code, 401)
        self.assertEqual(self.client.get("/api/calendar/jobs/anything").status_code, 401)
        self.assertEqual(self.client.get("/calendar/index.html").location, "/calendar/")
        self.assertEqual(self.client.get("/calendar/events.html").location, "/calendar/")
        self.login(3)
        with self.client.get("/calendar/events-data.json") as response:
            self.assertEqual(response.status_code, 200)
        for event in self.data():
            with self.client.get("/calendar/" + event["path"]) as response:
                allowed = event["scope"] == "public" and event["status"] == "planned"
                self.assertEqual(response.status_code, 200 if allowed else 404, event["path"])

    def test_job_ownership_and_revoked_permissions(self):
        self.login(1)
        response = self.send("POST", "/events", self.payload)
        job_id = response.json["id"]
        self.login(3)
        self.assertEqual(self.client.get("/api/calendar/jobs/" + job_id).status_code, 404)
        self.store.grant(self.admin, self.actor, "viewer")
        with self.registration.connection() as db:
            db.execute("DELETE FROM github_admin_grants WHERE user_id=1")
        with self.assertRaisesRegex(PublicationError, "撤销"):
            self.publisher.process(self.store.job(job_id))

    def test_member_reads_all_but_only_owner_can_write(self):
        self.login(4)
        capabilities = self.client.get("/api/calendar/session").json
        self.assertTrue(capabilities["canViewAll"])
        self.assertFalse(capabilities["canEdit"])
        self.assertEqual(len(self.client.get("/api/calendar/events").json["events"]), len(self.data()))
        self.assertEqual(self.send("POST", "/events", self.payload | {"status": "tentative"}).status_code, 403)
        self.login(1)
        self.assertTrue(self.client.get("/api/calendar/session").json["isOwner"])
        self.assertEqual(self.send("POST", "/events", self.payload | {"status": "tentative"}).status_code, 202)

    def test_expired_unlinked_and_local_roles_cannot_grant_access(self):
        self.login(1)
        with self.registration.connection() as db:
            db.execute("UPDATE github_admin_grants SET valid_until=0 WHERE user_id=1")
        self.assertFalse(self.client.get("/api/calendar/session").json["canEdit"])
        self.assertFalse(owner_access(self.registration.path, 1))
        self.login(4)
        with self.registration.connection() as db:
            db.execute("DELETE FROM github_accounts WHERE user_id=4")
        self.assertFalse(self.client.get("/api/calendar/session").json["canViewAll"])
        self.store.grant(self.admin, self.accounts[4], "admin")
        self.assertFalse(self.client.get("/api/calendar/session").json["canEdit"])
        self.app.extensions.pop("registration_store")
        self.assertFalse(self.client.get("/api/calendar/session").json["canEdit"])

    def test_api_conflict_and_schema_validation(self):
        self.login(1)
        event = self.data()[0]
        self.assertEqual(self.send("PATCH", "/events/" + event["uid"],
                                   {"version": "x" * 64, "title": "修改 / Changed"}).status_code, 409)
        for payload in ({"command": "anything"}, {"title": "no english"}, self.payload | {"scope": "../x"},
                        self.payload | {"alarmMinutes": True}, self.payload | {"sourceUrl": "javascript:x"},
                        self.payload | {"alarmMode": ["set"]}):
            self.assertEqual(self.send("POST", "/events", payload).status_code, 422, payload)

    def test_bilingual_validation_rejects_before_queueing_add_or_update(self):
        self.login(1)
        event = self.data()[0]
        for key in ("title", "location"):
            for value in ("H4-103 / H4-103", "English / English", "中文 / 中文",
                          "中文 / ", " / English", "English / 中文"):
                for method, path, payload in (
                    ("POST", "/events", self.payload | {key: value}),
                    ("PATCH", "/events/" + event["uid"],
                     {"version": event["version"], key: value}),
                ):
                    with self.subTest(key=key, value=value, method=method):
                        response = self.send(method, path, payload)
                        self.assertEqual(response.status_code, 422)
                        self.assertIn("左侧须含中文", response.json["error"])
        self.assertIsNone(self.store.next_job())
        for location in ("", "H4-103 室 / Room H4-103"):
            response = self.send("POST", "/events", self.payload | {"location": location})
            self.assertEqual(response.status_code, 202)

    def test_invalid_source_text_never_pushes_or_activates(self):
        before = self.git("rev-parse", "HEAD", cwd=self.remote)
        active = (self.state / "current").readlink()
        original = self.publisher.apply

        def apply_invalid(root, job):
            original(root, job)
            event = next(item for item in snapshot(root) if item["uid"] == job["uid"])
            path = root / event["path"]
            calendar = Calendar.from_ical(path.read_bytes())
            calendar.walk("VEVENT")[0]["LOCATION"] = "H4-103 / H4-103"
            path.write_bytes(calendar.to_ical())

        job_id = self.store.enqueue(self.actor, "add", "test@beta", self.payload)
        with patch.object(self.publisher, "apply", side_effect=apply_invalid):
            with self.assertRaisesRegex(PublicationError, "LOCATION"):
                self.publisher.process(self.store.job(job_id))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.remote), before)
        self.assertEqual((self.state / "current").readlink(), active)

    def test_role_management_is_not_exposed_by_calendar(self):
        self.login(2)
        self.assertEqual(self.client.get("/api/calendar/roles").status_code, 404)
        self.assertEqual(self.send("PUT", "/roles", {"userId": 3, "role": "editor"}).status_code, 404)
        self.assertEqual(self.store.role(3), "viewer")
        with self.client.get("/calendar/") as response:
            self.assertNotIn(b'roles-open', response.data)
            self.assertNotIn(b'role-form', response.data)
        with self.assertRaises(ValueError):
            self.store.grant(self.admin, self.admin, "viewer")

    def test_idempotent_write_and_other_user_reuse(self):
        self.login(1)
        headers = {"X-CSRF-Token": "csrf-test", "Idempotency-Key": "a" * 32}
        first = self.client.post("/api/calendar/events", json=self.payload, headers=headers)
        second = self.client.post("/api/calendar/events", json=self.payload, headers=headers)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json["id"], second.json["id"])
        self.assertEqual(self.store.job(first.json["id"])["uid"], f"{'a' * 32}@calendar.betasdc")
        self.assertEqual(self.client.post("/api/calendar/events", json=self.payload | {"title": "不同 / Different"},
                                         headers=headers).status_code, 409)
        self.login(2)
        self.assertEqual(self.client.post("/api/calendar/events", json=self.payload, headers=headers).status_code, 409)

    def test_create_update_scope_confirm_and_delete(self):
        job_id = self.publish(payload=self.payload | {"status": "tentative"})
        event = next(item for item in self.data() if item["uid"] == "test@beta")
        version = event["version"]
        self.assertEqual(event["status"], "tentative")
        self.assertEqual(event["alarms"], ["-PT10M"])
        self.publish("update", payload={"version": version, "start": "2027-01-02T12:00",
                                      "scope": "internal", "status": "planned", "location": ""})
        event = next(item for item in self.data() if item["uid"] == "test@beta")
        self.assertNotEqual(event["version"], version)
        self.assertTrue(event["path"].startswith("internal/2027/01/"))
        self.assertEqual(event["end"], "2027-01-02T13:00:00+08:00")
        self.assertEqual(event["alarms"], ["-PT10M"])
        self.publish("delete", payload={"version": event["version"]})
        self.assertFalse(any(item["uid"] == "test@beta" for item in self.data()))
        self.assertIn(self.store.job(job_id)["commit_sha"], self.git("log", "--format=%H", cwd=self.remote))

    def test_all_day_exclusive_end_and_range_overlap(self):
        self.publish(payload=self.payload | {"start": "2026-12-01", "end": "2026-12-03"})
        event = next(item for item in self.data() if item["uid"] == "test@beta")
        self.assertTrue(event["allDay"])
        first = self.client.get("/api/calendar/events?start=2026-12-02&end=2026-12-03").json["events"]
        last = self.client.get("/api/calendar/events?start=2026-12-03&end=2026-12-04").json["events"]
        self.assertIn("test@beta", [item["uid"] for item in first])
        self.assertNotIn("test@beta", [item["uid"] for item in last])
        self.assertEqual(self.client.get("/api/calendar/events?start=bad").status_code, 422)

    def test_crash_after_push_reconciles_without_duplicate(self):
        job_id = self.store.enqueue(self.actor, "add", "test@beta", self.payload)
        with patch.object(self.publisher, "activate", side_effect=OSError("crash")):
            with self.assertRaises(OSError):
                self.publisher.process(self.store.job(job_id))
        self.assertEqual(self.store.job(job_id)["state"], "running")
        count = len(self.git("log", "--format=%H", cwd=self.remote).splitlines())
        self.publisher.process(self.store.job(job_id))
        self.assertEqual(self.store.job(job_id)["state"], "succeeded")
        self.assertEqual(len(self.git("log", "--format=%H", cwd=self.remote).splitlines()), count)
        self.assertEqual(len([item for item in self.data() if item["uid"] == "test@beta"]), 1)

    def test_conflicting_editor_preserves_active_release(self):
        self.publish()
        event = next(item for item in self.data() if item["uid"] == "test@beta")
        self.publish("update", payload={"version": event["version"], "title": "更新 / Update"})
        active = (self.state / "current").readlink()
        job_id = self.store.enqueue(self.actor, "update", event["uid"],
                                    {"version": event["version"], "title": "冲突 / Conflict"})
        with self.assertRaisesRegex(PublicationError, "修改"):
            self.publisher.process(self.store.job(job_id))
        self.assertEqual((self.state / "current").readlink(), active)

    def test_build_failure_never_pushes(self):
        before = self.git("rev-parse", "HEAD", cwd=self.remote)
        job_id = self.store.enqueue(self.actor, "add", "test@beta", self.payload)
        with patch("server.publisher.build_site", side_effect=ValueError("invalid build")):
            with self.assertRaises(ValueError):
                self.publisher.process(self.store.job(job_id))
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.remote), before)

    def test_push_failure_and_unknown_outcome_never_activate(self):
        active = (self.state / "current").readlink()
        original = run
        def fail_push(args, **kwargs):
            if args[:2] == ["git", "push"]:
                raise PublicationError("offline")
            return original(args, **kwargs)
        job_id = self.store.enqueue(self.actor, "add", "test@beta", self.payload)
        with patch("server.publisher.run", side_effect=fail_push):
            with self.assertRaises(PublicationError):
                self.publisher.process(self.store.job(job_id))
        self.assertEqual((self.state / "current").readlink(), active)
        def fail_both(args, **kwargs):
            if args[:2] in (["git", "push"], ["git", "fetch"]):
                raise PublicationError("offline")
            return original(args, **kwargs)
        with patch("server.publisher.run", side_effect=fail_both):
            with self.assertRaises(RetryPublication):
                self.publisher.process(self.store.job(job_id))
        self.assertEqual(self.store.job(job_id)["state"], "running")

    def test_remote_advances_during_push_without_overwriting_it(self):
        active = (self.state / "current").readlink()
        original = run
        raced = False
        def advance_remote(args, **kwargs):
            nonlocal raced
            if args[:2] == ["git", "push"] and not raced:
                raced = True
                other = self.root / "other"
                original(["git", "clone", str(self.remote), str(other)])
                self.publisher.cli(other, "add", "--uid=external@beta", "--scope=public",
                                   "--title=外部更改 / External change",
                                   "--start=2026-12-02", "--days=1")
                original(["git", "add", "."], cwd=other)
                original(["git", "commit", "-m", "External concurrent writer"],
                         cwd=other, env=self.publisher.env)
                original(["git", "push", "origin", "main"], cwd=other)
            return original(args, **kwargs)
        job_id = self.store.enqueue(self.actor, "add", "test@beta", self.payload)
        with patch("server.publisher.run", side_effect=advance_remote):
            with self.assertRaisesRegex(PublicationError, "冲突"):
                self.publisher.process(self.store.job(job_id))
        self.assertEqual((self.state / "current").readlink(), active)
        self.publisher.sync()
        self.assertIn("external@beta", [item["uid"] for item in self.data()])
        self.assertNotIn("test@beta", [item["uid"] for item in self.data()])

    def test_external_changes_sync_and_property_preservation(self):
        self.publish()
        with self.publisher.checkout() as root:
            event = next(item for item in snapshot(root) if item["uid"] == "test@beta")
            source = root / event["path"]
            from icalendar import Calendar
            calendar = Calendar.from_ical(source.read_bytes())
            entry = calendar.walk("VEVENT")[0]
            entry.add("X-CUSTOM", "preserve-me")
            entry.add("ATTACH", "https://example.com/info.pdf")
            source.write_bytes(calendar.to_ical())
            self.git("add", ".", cwd=root)
            run(["git", "commit", "-m", "External edit"], cwd=root, env=self.publisher.env)
            self.git("push", "origin", "HEAD:main", cwd=root)
        self.publisher.sync()
        event = next(item for item in self.data() if item["uid"] == "test@beta")
        self.publish("update", payload={"version": event["version"], "title": "保留属性 / Preserve"})
        raw = (self.state / "current" / next(item["path"] for item in self.data() if item["uid"] == "test@beta")).read_text()
        self.assertIn("X-CUSTOM:preserve-me", raw)
        self.assertIn("ATTACH:https://example.com/info.pdf", raw)
        self.assertIn("BEGIN:VALARM", raw)


if __name__ == "__main__":
    unittest.main()
