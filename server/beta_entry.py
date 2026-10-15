"""Gunicorn factory wrapping the existing BETA authentication application."""
import os
from pathlib import Path
import sqlite3

from .api import register_calendar


def create_app():
    from server.registration import create_app as create_registration_app
    from server.registration.auth import current_account, csrf_token

    app = create_registration_app()

    def current_user():
        account = current_account()
        if account:
            return app.extensions["registration_store"].find_account(account["username"])
        return None

    def lookup(user_id):
        with app.extensions["registration_store"].connection() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT id,username FROM registrations "
                             "WHERE id=? AND email_verified_at IS NOT NULL", (user_id,)).fetchone()
            return dict(row) if row else None

    register_calendar(app, state=Path(os.environ.get("CALENDAR_STATE", "/var/lib/betasdc-calendar")),
                      current_user=current_user, lookup_account=lookup, csrf_token=csrf_token)
    return app
