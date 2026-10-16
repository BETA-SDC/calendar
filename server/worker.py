"""Run with python -m calendar_service.worker (see deployment install script)."""
import argparse
from contextlib import closing
import logging
import os
from pathlib import Path
import signal
import sqlite3
import time

from .publisher import PublicationError, Publisher, RetryPublication
from .store import Store


def owner_access(database, user_id):
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        return connection.execute(
            "SELECT 1 FROM github_admin_grants a JOIN github_accounts g ON g.user_id=a.user_id "
            "WHERE a.user_id=? AND a.valid_until>?",
            (user_id, int(time.time())),
        ).fetchone() is not None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=Path(os.environ.get("CALENDAR_STATE", "/var/lib/betasdc-calendar")))
    parser.add_argument("--remote", default=os.environ.get("CALENDAR_REMOTE", "git@github.com:BETA-SDC/calendar.git"))
    parser.add_argument("--branch", default="main")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--registration-database", type=Path,
                        default=Path(os.environ.get(
                            "REGISTRATION_DATABASE", "/var/lib/betasdc/registrations.sqlite3")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    store = Store(args.state / "calendar.sqlite3")
    publisher = Publisher(args.state, args.remote, store, args.branch,
                          can_manage=lambda user_id: owner_access(args.registration_database, user_id))
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    last_sync = 0
    while not stopping:
        job = store.next_job()
        try:
            if job:
                publisher.process(job)
                last_sync = time.monotonic()
            elif time.monotonic() - last_sync > 60 or args.once:
                publisher.sync()
                last_sync = time.monotonic()
        except RetryPublication:
            logging.warning("Publication outcome pending reconciliation: %s", job["id"])
            time.sleep(5)
        except (PublicationError, ValueError) as exc:
            if job:
                store.finish(job["id"], "failed", error=str(exc))
            logging.warning("%s", exc)
            time.sleep(2)
        except Exception:
            # Leave running jobs durable: restart/retry reconciles their Git trailer.
            logging.exception("Calendar worker failed; retaining publication request")
            if args.once:
                raise
            time.sleep(5)
        if args.once:
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
