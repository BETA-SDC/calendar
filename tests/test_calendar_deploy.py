import importlib.util
import json
from pathlib import Path
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CalendarDeployTest(unittest.TestCase):
    def test_existing_upgrade_installs_and_rolls_back_python_scripts(self):
        source_script = (ROOT / "deploy/upgrade-existing.sh").read_text()
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                installed = root / "installed"
                staged = root / "staged"
                state = root / "state"
                backups = root / "backups"
                binaries = root / "bin"
                for directory in (backups, binaries, state / "release", installed / ".venv/bin"):
                    directory.mkdir(parents=True)
                for directory in ("server", "scripts", "web"):
                    (installed / directory).mkdir()
                    (staged / directory).mkdir(parents=True)
                for path in ("server/api.py", "scripts/build_feeds.py",
                             "scripts/calendar_cli.py", "web/calendar.js"):
                    (installed / path).write_text("old")
                    (staged / path).write_text("new")
                (state / "release/calendar.js").write_text("new")
                (state / "release/revision.json").write_text('{"commit":"expected"}')
                (state / "current").symlink_to("release", target_is_directory=True)
                (installed / ".venv/bin/python").symlink_to(sys.executable)
                mocks = {
                    "id": "printf '0\\n'",
                    "hostname": "printf '550c\\n'",
                    "sleep": "exit 0",
                    "runuser": "exit 0",
                    "systemctl": 'if [ "$1" = kill ] && [ "$FAIL_RELOAD" = 1 ]; then exit 1; fi',
                    "curl": """printf '{"canViewAll":true,"canEdit":false}\\n'""",
                }
                for name, content in mocks.items():
                    path = binaries / name
                    path.write_text("#!/bin/sh\n" + content + "\n")
                    path.chmod(0o755)
                script = root / "upgrade.sh"
                script.write_text(
                    source_script.replace("/opt/betasdc-calendar", str(installed))
                    .replace("/var/lib/betasdc-calendar", str(state))
                    .replace("/var/backups/betasdc", str(backups))
                    .replace("install -o root -g root -m 644", "install -m 644")
                    .replace('chown -R root:root "$ROOT/web"', ":")
                )
                result = subprocess.run(
                    ["sh", str(script), str(staged), "expected"],
                    env=dict(os.environ, PATH=f"{binaries}:{os.environ['PATH']}",
                             FAIL_RELOAD=str(int(fail))),
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode == 0, not fail, result.stderr)
                for path in ("server/api.py", "scripts/build_feeds.py",
                             "scripts/calendar_cli.py", "web/calendar.js"):
                    self.assertEqual((installed / path).read_text(), "old" if fail else "new")
                backup = next(backups.glob("calendar-upgrade-*"))
                with tarfile.open(backup / "code.tar") as archive:
                    self.assertIn("scripts/build_feeds.py", archive.getnames())
                    self.assertIn("scripts/calendar_cli.py", archive.getnames())
                self.assertEqual((state / "current").readlink(), Path("release"))

    def test_nginx_include_is_idempotent_and_preserves_existing_host(self):
        module = load("nginx_calendar")
        original = "http {\n    server {\n        server_name register.betasdc.duckdns.org;\n        allow 10.16.112.0/20;\n        location / {\n        }\n    }\n}\n"
        configured = module.configure(original)
        self.assertEqual(module.configure(configured), configured)
        self.assertIn("server_name register.betasdc.duckdns.org;", configured)
        self.assertEqual(configured.count("include /etc/betasdc/calendar.nginx.conf;"), 1)
        self.assertIn("client_max_body_size 32k;", configured)
        self.assertEqual(configured.count("allow 10.16.112.0/20;"), 1)
        self.assertNotIn("allow 10.17.0.0/18;", configured)
        with self.assertRaises(ValueError):
            module.configure("unrecognized layout")

    def test_calendar_host_has_no_ip_whitelist_and_preserves_other_checks(self):
        config = (ROOT / "deploy/calendar.nginx.conf").read_text()
        self.assertIn("allow all;", config)
        self.assertNotIn("deny all;", config)
        self.assertNotIn("allow 10.", config)
        self.assertIn('if ($http_host != "calendar.betasdc.duckdns.org")', config)
        self.assertIn("ssl_protocols TLSv1.2 TLSv1.3;", config)
        self.assertIn("limit_conn connections 10;", config)
        self.assertIn("client_max_body_size 32k;", config)

    def test_wheel_manifest_checks_content_and_requirements(self):
        module = load("wheels")
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            wheel = output / "example.whl"
            wheel.write_bytes(b"test-wheel")
            manifest = {"requirements": module.requirements_digest(),
                        "files": {wheel.name: module.hashlib.sha256(wheel.read_bytes()).hexdigest()}}
            (output / "manifest.json").write_text(json.dumps(manifest))
            module.verify(output)
            with patch.object(module, "requirements_digest", return_value="changed"):
                with self.assertRaises(ValueError):
                    module.verify(output)
            wheel.write_bytes(b"damaged-wheel")
            with self.assertRaises(ValueError):
                module.verify(output)
