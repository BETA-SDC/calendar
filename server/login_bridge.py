"""Host routing and a private session key for the dedicated calendar host."""
import fcntl
import os
import re
import stat

REGISTRATION_HOST = "account.betasdc.duckdns.org"
CALENDAR_HOST = "calendar.betasdc.duckdns.org"
CALENDAR_NETWORKS = ("0.0.0.0/0", "::/0")
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
    def __init__(self, account_wsgi, calendar_wsgi, sites_wsgi=None):
        self.account_wsgi = account_wsgi
        self.calendar_wsgi = calendar_wsgi
        self.sites_wsgi = sites_wsgi or {}

    def __call__(self, environ, start_response):
        calendar_host = environ.get("HTTP_HOST", "").lower() == CALENDAR_HOST
        # Read-only top-level entry pages may be linked from other sites.
        # Keep Origin, network, API and all mutation checks unchanged.
        if (calendar_host and environ.get("REQUEST_METHOD") == "GET"
                and environ.get("PATH_INFO") in {
                    "/", "/calendar/", "/calendar/calendar.html",
                    "/login", "/account", "/register", "/verify",
                }
                and environ.get("HTTP_SEC_FETCH_SITE") == "cross-site"
                and environ.get("HTTP_SEC_FETCH_MODE") == "navigate"
                and environ.get("HTTP_SEC_FETCH_DEST") == "document"):
            environ = environ.copy()
            environ.pop("HTTP_SEC_FETCH_SITE")
        app = self.sites_wsgi.get(environ.get("HTTP_HOST", "").lower(),
                                  self.calendar_wsgi if calendar_host else self.account_wsgi)
        return app(environ, start_response)
