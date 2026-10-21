"""Register with a host Flask application using its validated account and CSRF callbacks."""
from datetime import date, datetime
import json
from pathlib import Path
import secrets
import time
import uuid
import re
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, current_app, jsonify, redirect, request, send_from_directory, session
from .publisher import validate_payload
from .store import Store


def register_calendar(app, *, state, current_user, csrf_token):
    state = Path(state)
    store = Store(state / "calendar.sqlite3")
    api = Blueprint("calendar_api", __name__, url_prefix="/api/calendar")
    pages = Blueprint("calendar_pages", __name__)
    app.extensions["calendar_store"] = store

    def user():
        return current_user()

    def account_access(account):
        if not account:
            return {"role": "viewer", "member": False, "owner": False}
        registration_store = current_app.extensions.get("registration_store")
        if registration_store is None:
            return {"role": "viewer", "member": False, "owner": False}
        now = int(time.time())
        with registration_store.connection() as connection:
            owner = connection.execute(
                "SELECT 1 FROM github_admin_grants a JOIN github_accounts g ON g.user_id=a.user_id "
                "WHERE a.user_id=? AND a.valid_until>?",
                (account["id"], now),
            ).fetchone() is not None
            member = connection.execute(
                "SELECT 1 FROM group_members m JOIN account_groups g ON g.id=m.group_id "
                "JOIN github_accounts a ON a.user_id=m.user_id "
                "WHERE m.user_id=? AND m.source='github' AND g.external_key=? AND g.archived=0 "
                "AND (m.valid_until IS NULL OR m.valid_until>?)",
                (account["id"], "github:org:BETA-SDC", now),
            ).fetchone() is not None
        return {"role": "owner" if owner else "member" if member else "viewer",
                "member": member or owner, "owner": owner}

    def require_owner():
        account = user()
        if not account:
            abort(401, description="请先登录。")
        if not account_access(account)["owner"]:
            abort(403, description="只有 BETA-SDC Owner 可以管理日历。")
        return account

    @api.before_request
    def protect():
        request.max_content_length = 32768
        if request.method in ("POST", "PATCH", "PUT", "DELETE"):
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not secrets.compare_digest(expected.encode(), supplied.encode()):
                abort(403, description="会话已失效，请刷新后重试。")
            if not request.is_json:
                abort(415, description="请求必须是 JSON。")

    @api.errorhandler(400)
    @api.errorhandler(401)
    @api.errorhandler(403)
    @api.errorhandler(404)
    @api.errorhandler(409)
    @api.errorhandler(415)
    @api.errorhandler(422)
    def error_response(error):
        return jsonify(error=error.description), error.code

    @api.get("/session")
    def capabilities():
        account = user()
        access = account_access(account)
        return jsonify(user={"id": account["id"], "username": account["username"]} if account else None,
                       role=access["role"], isMember=access["member"], isOwner=access["owner"],
                       canViewAll=access["member"], canEdit=access["owner"],
                       csrf_token=csrf_token(),
                       loginUrl=app.config.get("CALENDAR_LOGIN_URL", "/login"))

    def events():
        try:
            return json.loads((state / "current/server-events.json").read_text(encoding="utf-8"))["events"]
        except (FileNotFoundError, json.JSONDecodeError):
            abort(503, description="日历正在同步，请稍后重试。")

    def public_planned(event):
        return event["scope"] == "public" and event["status"] == "planned"

    @api.get("/events")
    def read_events():
        account = user()
        items = events()
        for key in ("start", "end"):
            if request.args.get(key):
                try:
                    datetime.fromisoformat(request.args[key].replace("Z", "+00:00"))
                except ValueError:
                    abort(422, description="日期范围无效。")
        def local_date(value):
            if len(value) == 10:
                return date.fromisoformat(value)
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Shanghai")).date()
        first = local_date(request.args["start"]) if request.args.get("start") else None
        last = local_date(request.args["end"]) if request.args.get("end") else None
        if first and last and first >= last:
            abort(422, description="结束日期须晚于开始日期。")
        access = account_access(account)
        can_view_all = access["member"]
        result = []
        for event in items:
            if not can_view_all and not public_planned(event):
                continue
            start = local_date(event["start"])
            end = local_date(event["end"]) if event["end"] else start
            if last and start >= last:
                continue
            if first and (end < first or (event["allDay"] and event["end"] and end == first)):
                continue
            result.append(event | {"actions": {
                "edit": access["owner"] and not event["recurring"],
                "delete": access["owner"],
            }})
        return jsonify(events=result)

    def queue(operation, uid=None):
        actor = require_owner()
        payload = request.get_json()
        try:
            validate_payload(payload, operation)
        except (ValueError, TypeError) as exc:
            abort(422, description=str(exc))
        job_id = request.headers.get("Idempotency-Key") or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            abort(422, description="发布请求编号无效。")
        previous = store.job(job_id)
        if previous:
            if (previous["user_id"] != actor["id"] or previous["operation"] != operation
                    or json.loads(previous["payload"]) != payload
                    or (operation != "add" and previous["uid"] != uid)):
                abort(409, description="发布请求编号已使用。")
            return jsonify(id=job_id, state=previous["state"]), 202
        if operation != "add":
            existing = next((event for event in events() if event["uid"] == uid), None)
            if existing is None:
                abort(404, description="活动不存在。")
            if existing["version"] != payload["version"]:
                abort(409, description="活动已被修改，请刷新后重新编辑。")
            if existing["recurring"] and operation != "delete":
                abort(422, description="重复活动请通过日历 CLI 维护。")
        uid = uid or f"{job_id}@calendar.betasdc"
        try:
            job_id = store.enqueue(actor, operation, uid, payload, job_id)
        except ValueError as exc:
            abort(409, description=str(exc))
        return jsonify(id=job_id, state="pending"), 202

    @api.post("/events")
    def create_event():
        return queue("add")

    @api.patch("/events/<path:uid>")
    def update_event(uid):
        return queue("update", uid)

    @api.delete("/events/<path:uid>")
    def delete_event(uid):
        return queue("delete", uid)

    @api.get("/jobs/<job_id>")
    def read_job(job_id):
        actor = user()
        if not actor:
            abort(401, description="请先登录。")
        job = store.job(job_id)
        if not job or (job["user_id"] != actor["id"] and not account_access(actor)["owner"]):
            abort(404, description="发布请求不存在。")
        return jsonify(id=job["id"], state=job["state"], commit=job["commit_sha"], error=job["error"])

    @pages.get("/calendar/")
    @pages.get("/calendar/<path:asset>")
    def calendar_page(asset="calendar.html"):
        # Administrative data must never be served as a public static asset.
        if (asset in {"server-events.json", "revision.json"}
                or asset.startswith(".") or ".." in Path(asset).parts):
            abort(404)
        # UI-only upgrades must not mutate an immutable published event release.
        if asset in {"calendar.html", "calendar.js", "calendar-validation.js", "workspace.css"}:
            return send_from_directory(Path(__file__).resolve().parents[1] / "web", asset)
        return send_from_directory(state / "current", asset)

    @pages.before_request
    def guest_pages():
        if account_access(user())["member"]:
            return None
        asset = (request.view_args or {}).get("asset", "calendar.html")
        if asset in {"index.html", "events.html"}:
            return redirect("/calendar/")
        if asset in {"calendar.html", "calendar-config.json", "calendar.css", "workspace.css",
                     "calendar.js", "calendar-preferences.js", "calendar-account.js", "calendar-validation.js",
                     "login.css", "login.js", "mark.png"}:
            return None
        if asset in {"vendor/fullcalendar.js", "vendor/fullcalendar-locales.js",
                     "vendor/fullcalendar-luxon.js", "vendor/luxon.js", "vendor/lucide.js"}:
            return None
        if asset.endswith(".ics") and any(
                public_planned(event) and event.get("path") == asset for event in events()):
            return None
        abort(404)

    @pages.get("/calendar/calendar-config.json")
    def calendar_config():
        return jsonify(api=True)

    @pages.get("/calendar/calendar-data.json")
    @pages.get("/calendar/events-data.json")
    def filtered_calendar_data():
        asset = request.path.rsplit("/", 1)[-1]
        try:
            payload = json.loads((state / "current" / asset).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            abort(503, description="日历正在同步，请稍后重试。")
        if account_access(user())["member"]:
            return jsonify(payload)
        if asset == "calendar-data.json":
            payload["feeds"] = {
                key: value for key, value in payload.get("feeds", {}).items()
                if key.startswith("public@planned")
            }
            payload["restrictedIncluded"] = False
        else:
            payload["events"] = [
                event for event in payload.get("events", []) if public_planned(event)
            ]
            payload["restrictedIncluded"] = False
        return jsonify(payload)

    # FullCalendar injects its own stylesheet and sets element style attributes.
    # Limit the host CSP relaxation to calendar documents, never account pages.
    @pages.after_request
    def calendar_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://avatars.githubusercontent.com; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        return response

    @api.after_request
    def private_api(response):
        response.headers["Cache-Control"] = "no-store"
        return response

    app.register_blueprint(api)
    app.register_blueprint(pages)
    # Host after_request runs after blueprint handlers, so apply this last in that chain.
    original_after = app.after_request_funcs.setdefault(None, [])
    def final_calendar_headers(response):
        if request.path.startswith("/calendar/"):
            return calendar_headers(response)
        return response
    original_after.insert(0, final_calendar_headers)
    return store
