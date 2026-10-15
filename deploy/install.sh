#!/bin/sh
# Usage: sudo sh deploy/install.sh auto DEPLOY_KEY KNOWN_HOSTS
# An existing username may replace auto; a token file may replace both key files.
set -eu
test "$(id -u)" = 0 || { echo "Run as root." >&2; exit 1; }
test "$#" = 2 || test "$#" = 3 || { echo "Usage: $0 ADMIN_USERNAME TOKEN_FILE (or DEPLOY_KEY KNOWN_HOSTS)" >&2; exit 1; }
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
install_root=/opt/betasdc-calendar
test "$source_dir" != "$install_root" || { echo "Run from a staging checkout." >&2; exit 1; }
test -f "$2"
if test "$#" = 3; then test -f "$3"; fi
backup="/var/backups/betasdc-calendar/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup"
chmod 700 "$backup"
if test -d "$install_root"; then cp -a "$install_root" "$backup/app"; fi
if test -f /etc/systemd/system/betasdc.service.d/calendar.conf; then
  cp /etc/systemd/system/betasdc.service.d/calendar.conf "$backup/calendar.conf"
fi
if test -f /etc/betasdc/calendar.env; then cp /etc/betasdc/calendar.env "$backup/calendar.env"; fi
if test -f /etc/systemd/system/betasdc-calendar.service; then cp /etc/systemd/system/betasdc-calendar.service "$backup/worker.service"; fi
cp /etc/betasdc/nginx.conf "$backup/nginx.conf"
mkdir -p "$install_root"
# Copy tracked sources only; never copy a developer's venv or generated site.
git -c safe.directory="$source_dir" -C "$source_dir" archive HEAD | tar -x -C "$install_root"
ln -sfn server "$install_root/calendar_service"
python3 -m venv "$install_root/.venv"
"$install_root/.venv/bin/pip" install -r "$install_root/requirements-server.txt" gunicorn==23.0.0
install -d -o betasdc -g www-data -m 700 /var/lib/betasdc-calendar
if test "$#" = 3; then
  install -o betasdc -g www-data -m 600 "$2" /var/lib/betasdc-calendar/deploy-key
  install -o betasdc -g www-data -m 600 "$3" /var/lib/betasdc-calendar/known_hosts
  install -m 600 "$install_root/deploy/calendar.env" /etc/betasdc/calendar.env
else
  install -o betasdc -g www-data -m 600 "$2" /var/lib/betasdc-calendar/github-token
  install -m 600 "$install_root/deploy/calendar-token.env" /etc/betasdc/calendar.env
fi
install -d -m 755 /etc/systemd/system/betasdc.service.d
install -m 644 "$install_root/deploy/calendar.conf" /etc/systemd/system/betasdc.service.d/calendar.conf
install -m 644 "$install_root/deploy/betasdc-calendar.service" /etc/systemd/system/betasdc-calendar.service
(
  cd "$install_root"
  if test "$1" = auto; then
    runuser -u betasdc -- .venv/bin/python -m calendar_service.admin --auto
  else
    runuser -u betasdc -- .venv/bin/python -m calendar_service.admin --username "$1"
  fi
)
"$install_root/.venv/bin/python" "$install_root/deploy/nginx_calendar.py" /etc/betasdc/nginx.conf
if ! /usr/sbin/nginx -e stderr -t -c /etc/betasdc/nginx.conf; then
  cp "$backup/nginx.conf" /etc/betasdc/nginx.conf
  echo "Nginx validation failed; restored configuration." >&2
  exit 1
fi
systemctl daemon-reload
systemctl enable betasdc-calendar
systemctl restart betasdc-calendar
attempt=0
while test ! -f /var/lib/betasdc-calendar/current/calendar.html; do
  attempt=$((attempt + 1))
  if test "$attempt" -ge 90; then
    echo "Initial sync failed. Inspect: journalctl -u betasdc-calendar. Backup: $backup" >&2
    exit 1
  fi
  sleep 1
done
systemctl restart betasdc
systemctl reload betasdc-nginx
systemctl is-active betasdc betasdc-calendar
echo "Installed. Backup: $backup"
echo "Calendar: https://register.betasdc.duckdns.org/calendar/"
