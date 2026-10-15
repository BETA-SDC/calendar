"""Add the calendar API override and dedicated virtual host include."""
from pathlib import Path
import sys

def configure(content):
    marker = "        location ^~ /api/calendar/ {"
    if marker not in content:
        anchor = "        location / {"
        if content.count(anchor) != 1:
            raise ValueError("Unexpected nginx layout; preserve config and inspect manually.")
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
        content = content.replace(anchor, location + anchor)
    include = "    include /etc/betasdc/calendar.nginx.conf;"
    if include not in content:
        before, closing = content.rsplit("}", 1)
        if closing.strip():
            raise ValueError("Unexpected nginx closing block.")
        content = before + include + "\n}\n"
    return content


if __name__ == "__main__":
    path = Path(sys.argv[1])
    path.write_text(configure(path.read_text()))
