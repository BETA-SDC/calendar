import contextlib
from contextlib import closing
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from werkzeug.security import check_password_hash

from server.admin import bootstrap
from server.store import Store


class CalendarAdminTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "state"
        self.accounts = Path(self.temp.name) / "accounts.sqlite3"
        with closing(sqlite3.connect(self.accounts)) as db, db:
            db.execute("CREATE TABLE registrations (id INTEGER PRIMARY KEY, username TEXT UNIQUE, "
                       "email TEXT UNIQUE, password_hash TEXT, email_verified_at INTEGER)")

    def account(self, username, verified=True, password="hash"):
        with closing(sqlite3.connect(self.accounts)) as db, db:
            cursor = db.execute("INSERT INTO registrations(username,email,password_hash,email_verified_at) "
                                "VALUES(?,?,?,?)", (username, username + "@example.invalid", password,
                                                   1 if verified else None))
            return {"id": cursor.lastrowid, "username": username}

    def test_select_existing_verified_account_and_preserve_admin(self):
        self.account("unverified", verified=False)
        self.account("no-password", password=None)
        first = self.account("first")
        later = self.account("later")
        self.assertEqual(bootstrap(self.state, self.accounts), first)
        store = Store(self.state / "calendar.sqlite3")
        store.grant(first, later, "admin")
        store.grant(later, first, "viewer")
        self.assertEqual(bootstrap(self.state, self.accounts), later)
        self.assertFalse((self.state / "bootstrap-account.json").exists())

    def test_create_login_capable_private_account_once(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            account = bootstrap(self.state, self.accounts)
        credentials = self.state / "bootstrap-account.json"
        values = json.loads(credentials.read_text())
        self.assertEqual(credentials.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(values["password"], output.getvalue())
        with closing(sqlite3.connect(self.accounts)) as db, db:
            row = db.execute("SELECT password_hash,email_verified_at FROM registrations WHERE id=?",
                             (account["id"],)).fetchone()
        self.assertTrue(check_password_hash(row[0], values["password"]))
        self.assertIsNotNone(row[1])
        self.assertEqual(bootstrap(self.state, self.accounts), account)
        self.assertEqual(json.loads(credentials.read_text()), values)

    def test_explicit_account_must_be_verified(self):
        self.account("unverified", verified=False)
        with self.assertRaises(ValueError):
            bootstrap(self.state, self.accounts, "unverified")
        with self.assertRaises(ValueError):
            bootstrap(self.state, self.accounts, "missing")
