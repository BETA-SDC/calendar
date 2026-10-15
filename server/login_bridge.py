"""Exchange short-lived login grants between the account and calendar hosts."""
import fcntl
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import time
from urllib.parse import urlencode

from flask import abort, redirect, request, send_from_directory, session

ACCOUNT_HOST = "register.betasdc.duckdns.org"
CALENDAR_HOST = "calendar.betasdc.duckdns.org"
STATE_PATTERN = re.compile(r"[a-f0-9]{64}")


def private_key(path):
    """Use a dedicated calendar key, never the account site's signing key."""
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as keyfile:
        fcntl.flock(keyfile, fcntl.LOCK_EX)
        info = os.fstat(keyfile.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError("Calendar session key must be private and service-owned.")
        key = keyfile.read()
        if not key:
            key = secrets.token_hex(32)
            keyfile.write(key)
            keyfile.flush()
            os.fsync(keyfile.fileno())
        if not STATE_PATTERN.fullmatch(key):
            raise ValueError("Invalid calendar session key.")
        return key


def install_bridge(account_app, calendar_app, store, current_user, establish_session):
    with store.connection() as db:
        db.execute("CREATE TABLE IF NOT EXISTS login_grants ("
                   "code_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,state TEXT NOT NULL,"
                   "expires_at INTEGER NOT NULL)")

    @account_app.get("/calendar/calendar-login.js")
    def account_login_script():
        return send_from_directory(Path(__file__).resolve().parents[1] / "web", "calendar-login.js")

    @calendar_app.before_request
    def calendar_entry():
        if request.path == "/":
            return redirect("/calendar/")
        if request.path in ("/login", "/account", "/register", "/verify"):
            return redirect("/calendar-login")
        if request.path.startswith("/api/") and not request.path.startswith("/api/calendar/"):
            abort(404)

    @calendar_app.get("/calendar-login")
    def calendar_login():
        state = secrets.token_hex(32)
        session["calendar_login_state"] = state
        session["calendar_login_started"] = int(time.time())
        return redirect(f"https://{ACCOUNT_HOST}/api/calendar/auth/authorize?" + urlencode({"state": state}))

    @account_app.get("/api/calendar/auth/authorize")
    def authorize():
        state = request.args.get("state", "")
        if not STATE_PATTERN.fullmatch(state):
            abort(400)
        account = current_user()
        if not account:
            return redirect("/login?" + urlencode({"calendar_state": state}))
        code = secrets.token_hex(32)
        now = int(time.time())
        with store.connection() as db:
            db.execute("DELETE FROM login_grants WHERE expires_at <= ?", (now,))
            db.execute("INSERT INTO login_grants VALUES (?,?,?,?)",
                       (hashlib.sha256(code.encode()).hexdigest(), account["id"], state, now + 60))
        return redirect(f"https://{CALENDAR_HOST}/api/calendar/auth/finish?" +
                        urlencode({"code": code, "state": state}))

    @calendar_app.get("/api/calendar/auth/finish")
    def finish():
        state, code = request.args.get("state", ""), request.args.get("code", "")
        expected = session.get("calendar_login_state", "")
        if (not STATE_PATTERN.fullmatch(state) or not STATE_PATTERN.fullmatch(code) or not expected
                or not secrets.compare_digest(state, expected)
                or int(time.time()) - session.get("calendar_login_started", 0) > 600):
            abort(403)
        with store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            grant = db.execute("SELECT user_id FROM login_grants WHERE code_hash=? AND state=? "
                               "AND expires_at > ?", (hashlib.sha256(code.encode()).hexdigest(),
                                                     state, int(time.time()))).fetchone()
            if not grant:
                abort(403)
            db.execute("DELETE FROM login_grants WHERE code_hash=?", (hashlib.sha256(code.encode()).hexdigest(),))
        establish_session(grant["user_id"])
        return redirect("/calendar/")

    @account_app.after_request
    def login_return(response):
        if (request.path in ("/login", "/account", "/register")
                and response.status_code == 200 and response.mimetype == "text/html"):
            state = request.args.get("calendar_state", "")
            query = "?" + urlencode({"state": state}) if STATE_PATTERN.fullmatch(state) else ""
            script = f'<script src="/calendar/calendar-login.js{query}" defer></script>'
            response.direct_passthrough = False
            response.set_data(response.get_data(as_text=True).replace("</body>", script + "</body>"))
            response.headers.pop("ETag", None)
        return response


class HostRouter:
    def __init__(self, account_wsgi, calendar_wsgi):
        self.account_wsgi = account_wsgi
        self.calendar_wsgi = calendar_wsgi

    def __call__(self, environ, start_response):
        app = self.calendar_wsgi if environ.get("HTTP_HOST", "").lower() == CALENDAR_HOST else self.account_wsgi
        return app(environ, start_response)
