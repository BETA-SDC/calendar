"""Git credential helper limited to this repository; never run directly for diagnostics."""
from pathlib import Path
import sys

if sys.argv[1:] != ["get"]:
    raise SystemExit(0)
fields = dict(line.rstrip("\n").split("=", 1) for line in sys.stdin if "=" in line)
if (fields.get("protocol") != "https" or fields.get("host") != "github.com"
        or fields.get("path", "").rstrip("/") not in ("BETA-SDC/calendar", "BETA-SDC/calendar.git")):
    raise SystemExit(0)
token = Path("/var/lib/betasdc-calendar/github-token").read_text().strip()
if not token or len(token) > 512 or not token.isascii() or any(c.isspace() for c in token):
    raise SystemExit("Invalid repository credential file")
print(f"username=x-access-token\npassword={token}\n")
