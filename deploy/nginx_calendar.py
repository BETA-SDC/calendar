"""Add only the calendar API body-size override to the existing host server."""
from pathlib import Path
import sys

path = Path(sys.argv[1])
content = path.read_text()
marker = "        location ^~ /api/calendar/ {"
if marker not in content:
    anchor = "        location / {"
    if content.count(anchor) != 1:
        raise SystemExit("Unexpected nginx layout; preserve config and inspect manually.")
    location = """        location ^~ /api/calendar/ {
            client_max_body_size 32k;
            proxy_pass http://registration_backend;
            proxy_http_version 1.1;
            proxy_set_header Host register.betasdc.duckdns.org;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header Connection "";
            proxy_connect_timeout 2s;
            proxy_read_timeout 15s;
            proxy_send_timeout 10s;
            proxy_buffering off;
        }
"""
    path.write_text(content.replace(anchor, location + anchor))
