#!/bin/sh
set -eu
test "$(id -u)" = 0
test "$#" = 1
backup=$1
test -d "$backup"
systemctl stop betasdc-calendar || true
if test -d "$backup/app"; then
  mv /opt/betasdc-calendar "/opt/betasdc-calendar.failed-$(date +%s)"
  cp -a "$backup/app" /opt/betasdc-calendar
fi
if test -f "$backup/calendar.conf"; then
  cp "$backup/calendar.conf" /etc/systemd/system/betasdc.service.d/calendar.conf
else
  rm -f /etc/systemd/system/betasdc.service.d/calendar.conf
fi
if test -f "$backup/calendar.env"; then cp "$backup/calendar.env" /etc/betasdc/calendar.env; fi
if test -f "$backup/worker.service"; then
  cp "$backup/worker.service" /etc/systemd/system/betasdc-calendar.service
else
  systemctl disable betasdc-calendar || true
  rm -f /etc/systemd/system/betasdc-calendar.service
fi
systemctl daemon-reload
if test -f "$backup/nginx.conf"; then
  cp "$backup/nginx.conf" /etc/betasdc/nginx.conf
  /usr/sbin/nginx -e stderr -t -c /etc/betasdc/nginx.conf
  systemctl reload betasdc-nginx
fi
systemctl restart betasdc
if test -f "$backup/worker.service"; then systemctl start betasdc-calendar; fi
systemctl is-active betasdc
# Preserve the SQLite audit database and all pushed ICS commits.
