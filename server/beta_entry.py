"""Gunicorn factory wrapping the existing BETA authentication application."""
import os
from pathlib import Path

from .api import register_calendar
from .login_bridge import CALENDAR_HOST, CALENDAR_NETWORKS, CAMPUS_NETWORKS, HostRouter, REGISTRATION_HOST, private_key


def create_app():
    from server.registration import create_app as create_registration_app
    from server.registration.auth import current_account, csrf_token

    state = Path(os.environ.get("CALENDAR_STATE", "/var/lib/betasdc-calendar"))
    state.mkdir(parents=True, exist_ok=True)
    app = create_registration_app(config={"REGISTRATION_NETWORKS": CAMPUS_NETWORKS})
    calendar_app = create_registration_app(config={
        "REGISTRATION_DOMAIN": CALENDAR_HOST,
        "REGISTRATION_NETWORKS": CALENDAR_NETWORKS,
        "SECRET_KEY": private_key(state / "calendar.session-key"),
        "GITHUB_CLIENT_ID": "",
        "CALENDAR_MEMBERS_ONLY": True,
    })

    def current_user():
        account = current_account()
        if account:
            from flask import current_app
            return current_app.extensions["registration_store"].find_account(account["username"])
        return None

    calendar_store = register_calendar(calendar_app, state=state, current_user=current_user,
                                      csrf_token=csrf_token)
    app.extensions["calendar_store"] = calendar_store
    @calendar_app.before_request
    def calendar_entry():
        from flask import abort, redirect, request, send_from_directory
        if request.path == "/":
            return redirect("/calendar/")
        if request.path in ("/register", "/verify"):
            return redirect(f"https://{REGISTRATION_HOST}{request.path}")
        if request.path in ("/login", "/account"):
            return send_from_directory(Path(__file__).resolve().parents[1] / "web", "login.html")
        if request.path in ("/api/register", "/api/signup/code",
                            "/api/verification/resend", "/api/verification/confirm",
                            "/api/github/link", "/api/github/unlink", "/api/github/callback"):
            abort(404)
    app.wsgi_app = HostRouter(app.wsgi_app, calendar_app.wsgi_app)
    return app
