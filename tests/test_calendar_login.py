from pathlib import Path
import tempfile
import unittest

from flask import Flask

from server.login_bridge import CALENDAR_HOST, HostRouter, REGISTRATION_HOST, private_key


class CalendarLoginTest(unittest.TestCase):
    def test_private_key_is_stable_and_private(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "calendar.session-key"
            first = private_key(path)
            self.assertEqual(private_key(path), first)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                private_key(path)

    def test_host_router_selects_only_the_calendar_host(self):
        account = Flask("account")
        calendar = Flask("calendar")

        @account.get("/")
        def account_page():
            return "account"

        @calendar.get("/")
        def calendar_page():
            return "calendar"

        client = account.test_client()
        client.application.wsgi_app = HostRouter(account.wsgi_app, calendar.wsgi_app)
        self.assertEqual(client.get("/", base_url=f"https://{REGISTRATION_HOST}").data, b"account")
        self.assertEqual(client.get("/", base_url=f"https://{CALENDAR_HOST}").data, b"calendar")
