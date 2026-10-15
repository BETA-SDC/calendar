from pathlib import Path
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlsplit

from flask import Flask, session

from server.login_bridge import ACCOUNT_HOST, CALENDAR_HOST, HostRouter, install_bridge, private_key
from server.store import Store


class CalendarLoginTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.account = Flask("accounts")
        self.account.secret_key = "account-only-key"
        self.calendar = Flask("calendar")
        self.calendar.secret_key = private_key(self.root / "session-key")
        self.store = Store(self.root / "calendar.sqlite3")

        @self.account.get("/login")
        @self.account.get("/account")
        def login():
            return "<html><body>Existing account page</body></html>"

        @self.account.get("/test-login")
        def test_login():
            session.clear()
            session["user"] = 42
            return "ok"

        @self.calendar.get("/")
        def old_root():
            return "Old root"

        @self.calendar.get("/test-user")
        def test_user():
            return {"user": session.get("user")}

        def current_user():
            return {"id": session["user"]} if session.get("user") else None

        def establish(user_id):
            session.clear()
            session["user"] = user_id

        install_bridge(self.account, self.calendar, self.store, current_user, establish)
        self.account.wsgi_app = HostRouter(self.account.wsgi_app, self.calendar.wsgi_app)
        self.client = self.account.test_client()

    def get(self, path, host=CALENDAR_HOST):
        return self.client.get(path, base_url="https://" + host)

    def authorized(self):
        begin = self.get("/calendar-login")
        self.get("/test-login", ACCOUNT_HOST)
        return self.get(begin.location, ACCOUNT_HOST)

    def test_central_login_then_single_use_return(self):
        begin = self.get("/calendar-login")
        unauthenticated = self.get(begin.location, ACCOUNT_HOST)
        self.assertTrue(unauthenticated.location.startswith("/login?calendar_state="))
        page = self.get(unauthenticated.location, ACCOUNT_HOST)
        self.assertIn(b"/calendar/calendar-login.js?state=", page.data)
        script = self.get("/calendar/calendar-login.js", ACCOUNT_HOST)
        self.assertEqual(script.status_code, 200)
        script.close()
        self.get("/test-login", ACCOUNT_HOST)
        result = self.get(begin.location, ACCOUNT_HOST)
        self.assertTrue(result.location.startswith(f"https://{CALENDAR_HOST}/api/calendar/auth/finish?"))
        # Account host cookies cannot authenticate the calendar host.
        self.assertIsNone(self.get("/test-user").json["user"])
        self.assertEqual(self.get(result.location).status_code, 302)
        self.assertEqual(self.get("/test-user").json["user"], 42)
        self.assertEqual(self.get(result.location).status_code, 403)
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM login_grants").fetchone()[0], 0)

    def test_grant_cannot_be_used_in_another_browser_or_with_another_state(self):
        authorized = self.authorized()
        another = self.account.test_client()
        self.assertEqual(another.get(authorized.location).status_code, 403)
        query = parse_qs(urlsplit(authorized.location).query)
        invalid = f"/api/calendar/auth/finish?code={query['code'][0]}&state={'a' * 64}"
        self.assertEqual(self.get(invalid).status_code, 403)
        self.assertEqual(self.get(authorized.location).status_code, 302)

    def test_expired_grant_is_rejected(self):
        authorized = self.authorized()
        with self.store.connection() as db:
            db.execute("UPDATE login_grants SET expires_at=?", (int(time.time()) - 1,))
        self.assertEqual(self.get(authorized.location).status_code, 403)

    def test_invalid_state_root_redirect_and_key_permissions(self):
        self.assertEqual(self.get("/api/calendar/auth/authorize?state=bad", ACCOUNT_HOST).status_code, 400)
        self.assertEqual(self.get("/").location, "/calendar/")
        self.assertEqual(self.get("/login").location, "/calendar-login")
        self.assertEqual(self.get("/api/login").status_code, 404)
        key = self.root / "session-key"
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(private_key(key), self.calendar.secret_key)
        self.assertNotEqual(self.account.secret_key, self.calendar.secret_key)
        key.chmod(0o644)
        with self.assertRaises(PermissionError):
            private_key(key)
