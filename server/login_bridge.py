"""Host routing and a private session key for the dedicated calendar host."""
import fcntl
import os
import re
import stat

from flask import request

REGISTRATION_HOST = "register.betasdc.duckdns.org"
CALENDAR_HOST = "calendar.betasdc.duckdns.org"
KEY_PATTERN = re.compile(r"[a-f0-9]{64}")


def private_key(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+") as keyfile:
        fcntl.flock(keyfile, fcntl.LOCK_EX)
        info = os.fstat(keyfile.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError("Calendar session key must be private and service-owned.")
        key = keyfile.read()
        if not key:
            key = os.urandom(32).hex()
            keyfile.write(key)
            keyfile.flush()
            os.fsync(keyfile.fileno())
        if not KEY_PATTERN.fullmatch(key):
            raise ValueError("Invalid calendar session key.")
        return key


class HostRouter:
    def __init__(self, account_wsgi, calendar_wsgi):
        self.account_wsgi = account_wsgi
        self.calendar_wsgi = calendar_wsgi

    def __call__(self, environ, start_response):
        app = (self.calendar_wsgi
               if environ.get("HTTP_HOST", "").lower() == CALENDAR_HOST
               else self.account_wsgi)
        return app(environ, start_response)
