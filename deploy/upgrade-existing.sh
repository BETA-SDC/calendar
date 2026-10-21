#!/bin/sh
# Update an existing Linux installation without changing listeners or user data.
set -eu
umask 077
[ "$(id -u)" = 0 ] && [ "$(hostname)" = 550c ] || exit 1
SOURCE=${1:?Provide a staged calendar checkout}
REVISION=${2:?Provide the expected Git revision}
ROOT=/opt/betasdc-calendar
STATE=/var/lib/betasdc-calendar
[ -f "$SOURCE/server/api.py" ] && [ -f "$SOURCE/web/calendar.js" ] || exit 1
[ -f "$SOURCE/scripts/build_feeds.py" ] && [ -f "$SOURCE/scripts/calendar_cli.py" ] || exit 1
BACKUP=$(mktemp -d /var/backups/betasdc/calendar-upgrade-XXXXXX)
tar -C "$ROOT" -cpf "$BACKUP/code.tar" server scripts web
readlink "$STATE/current" > "$BACKUP/current"
rollback() {
    result=$?
    if [ "$result" != 0 ]; then
        systemctl stop betasdc-calendar.service || true
        tar -C "$ROOT" -xpf "$BACKUP/code.tar"
        ln -s "$(cat "$BACKUP/current")" "$STATE/rollback.next"
        mv -Tf "$STATE/rollback.next" "$STATE/current"
        systemctl restart betasdc.service betasdc-calendar.service
        printf 'Upgrade failed; restored code and release. Backup: %s\n' "$BACKUP" >&2
    fi
}
trap rollback EXIT
systemctl stop betasdc-calendar.service
for directory in server scripts; do
    for file in "$SOURCE/$directory"/*.py; do
        install -o root -g root -m 644 "$file" "$ROOT/$directory/$(basename "$file")"
    done
done
cp -R "$SOURCE/web/." "$ROOT/web/"
chown -R root:root "$ROOT/web"
find "$ROOT/web" -type d -exec chmod 755 {} +
find "$ROOT/web" -type f -exec chmod 644 {} +
cd "$ROOT"
runuser -u betasdc -g www-data -- env CALENDAR_STATE="$STATE" PYTHONPATH=/opt/betasdc \
    "$ROOT/.venv/bin/python" -B -c \
    'import sys; sys.path.insert(0, "/opt/betasdc"); from calendar_service.beta_entry import create_app; create_app(); print("Application initialized")'
systemctl start betasdc-calendar.service
ready=false
for attempt in $(seq 1 60); do
    if cmp -s "$ROOT/web/calendar.js" "$STATE/current/calendar.js" &&
        "$ROOT/.venv/bin/python" -B -c \
        'import json,sys; sys.exit(json.load(open(sys.argv[1]))["commit"] != sys.argv[2])' \
        "$STATE/current/revision.json" "$REVISION"; then
        ready=true
        break
    fi
    sleep 2
done
[ "$ready" = true ]
systemctl kill --kill-who=main --signal=HUP betasdc.service
sleep 5
systemctl is-active --quiet betasdc.service betasdc-calendar.service
curl --noproxy '*' --retry 5 --retry-all-errors --retry-delay 2 \
    --connect-timeout 3 --max-time 15 -fsS \
    --resolve calendar.betasdc.duckdns.org:443:10.16.125.52 \
    https://calendar.betasdc.duckdns.org/api/calendar/session |
    "$ROOT/.venv/bin/python" -c \
    'import json,sys; data=json.load(sys.stdin); assert "canViewAll" in data and "canEdit" in data'
printf 'Calendar upgrade complete: %s\nBackup: %s\n' "$REVISION" "$BACKUP"
trap - EXIT
