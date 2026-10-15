import importlib.util
import json
from pathlib import Path
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
    def test_nginx_include_is_idempotent_and_preserves_existing_host(self):
        module = load("nginx_calendar")
        original = "http {\n    server {\n        server_name register.betasdc.duckdns.org;\n        location / {\n        }\n    }\n}\n"
        configured = module.configure(original)
        self.assertEqual(module.configure(configured), configured)
        self.assertIn("server_name register.betasdc.duckdns.org;", configured)
        self.assertEqual(configured.count("include /etc/betasdc/calendar.nginx.conf;"), 1)
        self.assertIn("client_max_body_size 32k;", configured)
        with self.assertRaises(ValueError):
            module.configure("unrecognized layout")

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
