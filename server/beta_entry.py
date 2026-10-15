"""Gunicorn factory wrapping the existing BETA authentication application."""
import os
from pathlib import Path
import sqlite3

from .api import register_calendar
from .login_bridge import CALENDAR_HOST, HostRouter, install_bridge, private_key


def create_app():
    from server.registration import create_app as create_registration_app
    from server.registration.auth import current_account, csrf_token, establish_session

    state = Path(os.environ.get("CALENDAR_STATE", "/var/lib/betasdc-calendar"))
    state.mkdir(parents=True, exist_ok=True)
    app = create_registration_app()
    calendar_app = create_registration_app(config={
        "REGISTRATION_DOMAIN": CALENDAR_HOST,
        "SECRET_KEY": private_key(state / "calendar.session-key"),
        "GITHUB_CLIENT_ID": "",
        "CALENDAR_LOGIN_URL": "/calendar-login",
    })

    def current_user():
        account = current_account()
        if account:
            from flask import current_app
            return current_app.extensions["registration_store"].find_account(account["username"])
        return None

    def lookup(user_id):
        with app.extensions["registration_store"].connection() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT id,username FROM registrations "
                             "WHERE id=? AND email_verified_at IS NOT NULL", (user_id,)).fetchone()
            return dict(row) if row else None

    store = register_calendar(app, state=state, current_user=current_user,
                              lookup_account=lookup, csrf_token=csrf_token)
    register_calendar(calendar_app, state=state, current_user=current_user,
                      lookup_account=lookup, csrf_token=csrf_token)
    install_bridge(app, calendar_app, store, current_user, establish_session)
    app.wsgi_app = HostRouter(app.wsgi_app, calendar_app.wsgi_app)
    return app
