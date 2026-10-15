from pathlib import Path
import ipaddress
import tempfile
import unittest

from flask import Flask

from server.login_bridge import CALENDAR_HOST, CALENDAR_NETWORKS, CAMPUS_NETWORKS, HostRouter, REGISTRATION_HOST, private_key


class CalendarLoginTest(unittest.TestCase):
    def test_calendar_network_policy_accepts_any_ipv4_or_ipv6_address(self):
        networks = [ipaddress.ip_network(value) for value in CALENDAR_NETWORKS]
        for address in ("10.17.7.116", "10.26.79.1", "192.168.1.1", "203.0.113.1",
                        "127.0.0.1", "2001:db8::1234", "::1"):
            self.assertTrue(any(ipaddress.ip_address(address) in network for network in networks), address)

    def test_confirmed_campus_subnet_without_broad_private_network_access(self):
        networks = [ipaddress.ip_network(value) for value in CAMPUS_NETWORKS]
        def allowed(value):
            return any(ipaddress.ip_address(value) in network for network in networks)
        for address in ("10.17.7.116", "10.17.63.254", "10.16.125.52", "10.17.128.1"):
            self.assertTrue(allowed(address), address)
        for address in ("10.17.64.1", "10.26.79.1", "192.168.1.1", "203.0.113.1"):
            self.assertFalse(allowed(address), address)

    def test_external_navigation_exception_is_read_only_and_calendar_only(self):
        def echo(environ, start_response):
            start_response("200 OK", [])
            return [environ.get("HTTP_SEC_FETCH_SITE", "absent").encode(),
                    b":", environ.get("HTTP_ORIGIN", "absent").encode()]
        router = HostRouter(echo, echo)
        base = {"HTTP_HOST": CALENDAR_HOST, "REQUEST_METHOD": "GET", "PATH_INFO": "/calendar/",
                "HTTP_SEC_FETCH_SITE": "cross-site", "HTTP_SEC_FETCH_MODE": "navigate",
                "HTTP_SEC_FETCH_DEST": "document", "HTTP_ORIGIN": "https://untrusted.invalid"}
        def result(environ):
            return b"".join(router(environ, lambda *_: None))
        self.assertEqual(result(base), b"absent:https://untrusted.invalid")
        self.assertEqual(base["HTTP_SEC_FETCH_SITE"], "cross-site")
        for overrides in ({"REQUEST_METHOD": "POST"}, {"PATH_INFO": "/api/calendar/events"},
                          {"HTTP_HOST": REGISTRATION_HOST}, {"HTTP_SEC_FETCH_MODE": "cors"},
                          {"HTTP_SEC_FETCH_DEST": "iframe"}):
            self.assertTrue(result(base | overrides).startswith(b"cross-site:"))

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

    def test_host_router_dispatches_explicit_shared_sites_without_wildcard(self):
        def handler(text):
            def app(environ, start_response):
                start_response("200 OK", [])
                return [text.encode()]
            return app
        router = HostRouter(handler("account"), handler("calendar"), {
            "nav.betasdc.duckdns.org": handler("navigation"),
            "profile.betasdc.duckdns.org": handler("profile"),
        })
        for host, expected in (("nav", b"navigation"), ("profile", b"profile"), ("unknown", b"account")):
            environ = {"HTTP_HOST": host + ".betasdc.duckdns.org"}
            self.assertEqual(b"".join(router(environ, lambda *_: None)), expected)
