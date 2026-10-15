"""Provision a calendar administrator through a trusted server command."""
import argparse
from contextlib import closing
import json
import os
import secrets
import sqlite3
from pathlib import Path

from werkzeug.security import generate_password_hash

from .store import Store


def bootstrap(state, accounts, username=None):
    store = Store(state / "calendar.sqlite3")
    with closing(sqlite3.connect(f"{accounts.resolve().as_uri()}?mode=rw", uri=True)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN IMMEDIATE")
        if username:
            row = db.execute("SELECT id,username FROM registrations WHERE username=? COLLATE NOCASE "
                             "AND email_verified_at IS NOT NULL", (username,)).fetchone()
            if not row:
                raise ValueError("账号不存在或邮箱尚未验证")
        else:
            row = None
            for existing in store.roles():
                if existing["role"] == "admin":
                    row = db.execute("SELECT id,username FROM registrations WHERE id=? "
                                     "AND email_verified_at IS NOT NULL", (existing["userId"],)).fetchone()
                    if row:
                        break
            if not row:
                row = db.execute("SELECT id,username FROM registrations WHERE email_verified_at IS NOT NULL "
                                 "AND password_hash IS NOT NULL AND password_hash != '' ORDER BY id LIMIT 1").fetchone()
            if not row:
                username = "calendar-admin-" + secrets.token_hex(4)
                password = secrets.token_urlsafe(32)
                # Local provisioning is explicitly authorized by the server operator.
                # The reserved address never receives verification or recovery mail.
                db.execute("INSERT INTO registrations(username,email,password_hash,email_verified_at) "
                           "VALUES(?,?,?,strftime('%s','now'))",
                           (username, username + "@calendar.invalid", generate_password_hash(password)))
                row = db.execute("SELECT id,username FROM registrations WHERE username=?", (username,)).fetchone()
                credentials = state / "bootstrap-account.json"
                fd = os.open(credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as output:
                    json.dump({"username": username, "password": password,
                               "note": "Local administrator; reserved email cannot receive mail."}, output)
                print(f"New account credentials: {credentials}")
        account = dict(row)
    if store.role(account["id"]) != "admin":
        store.grant(account, account, "admin")
    return account


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path("/var/lib/betasdc-calendar"))
    parser.add_argument("--accounts", type=Path, default=Path("/var/lib/betasdc/registrations.sqlite3"))
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--username")
    choice.add_argument("--auto", action="store_true")
    args = parser.parse_args()
    try:
        account = bootstrap(args.state, args.accounts, args.username)
    except ValueError as error:
        parser.error(str(error))
    print(f"Administrator granted: {account['username']} (ID {account['id']})")


if __name__ == "__main__":
    main()
