"""Register with a host Flask application using its validated account and CSRF callbacks."""
from datetime import date, datetime
import json
from pathlib import Path
import secrets
import uuid
import re
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, jsonify, request, send_from_directory, session
from .publisher import validate_payload
from .store import Store


def register_calendar(app, *, state, current_user, lookup_account, csrf_token):
    state = Path(state)
    store = Store(state / "calendar.sqlite3")
    api = Blueprint("calendar_api", __name__, url_prefix="/api/calendar")
    pages = Blueprint("calendar_pages", __name__)
    app.extensions["calendar_store"] = store

    def user():
        return current_user()

    def require(role="editor"):
        account = user()
        if not account:
            abort(401, description="请先登录。")
        actual = store.role(account["id"])
        if actual != "admin" and (role == "admin" or actual != "editor"):
            abort(403, description="没有日历编辑权限。")
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
        role = store.role(account["id"]) if account else "viewer"
        return jsonify(user={"id": account["id"], "username": account["username"]} if account else None,
                       role=role, canEdit=role in ("editor", "admin"), csrf_token=csrf_token())

    def events():
        try:
            return json.loads((state / "current/server-events.json").read_text(encoding="utf-8"))["events"]
        except (FileNotFoundError, json.JSONDecodeError):
            abort(503, description="日历正在同步，请稍后重试。")

    @api.get("/events")
    def read_events():
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
        role = store.role(user()["id"]) if user() else "viewer"
        result = []
        for event in items:
            start = local_date(event["start"])
            end = local_date(event["end"]) if event["end"] else start
            if last and start >= last:
                continue
            if first and (end < first or (event["allDay"] and event["end"] and end == first)):
                continue
            result.append(event | {"actions": {
                "edit": role in ("editor", "admin") and not event["recurring"],
                "delete": role in ("editor", "admin"),
            }})
        return jsonify(events=result)

    def queue(operation, uid=None):
        actor = require()
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
        if not job or (job["user_id"] != actor["id"] and store.role(actor["id"]) != "admin"):
            abort(404, description="发布请求不存在。")
        return jsonify(id=job["id"], state=job["state"], commit=job["commit_sha"], error=job["error"])

    @api.get("/roles")
    def read_roles():
        require("admin")
        return jsonify(roles=store.roles())

    @api.put("/roles")
    def grant():
        actor = require("admin")
        payload = request.get_json()
        if (not isinstance(payload, dict) or set(payload) != {"userId", "role"}
                or type(payload["userId"]) is not int or payload["userId"] < 1
                or payload["role"] not in ("viewer", "editor", "admin")):
            abort(422, description="授权参数无效。")
        account = lookup_account(payload["userId"])
        if not account:
            abort(422, description="账号不存在或尚未验证邮箱。")
        try:
            store.grant(actor, account, payload["role"])
        except ValueError as exc:
            abort(409, description=str(exc))
        return jsonify(ok=True)

    @pages.get("/calendar/")
    @pages.get("/calendar/<path:asset>")
    def calendar_page(asset="calendar.html"):
        # Administrative data must never be served as a public static asset.
        if (asset in {"server-events.json", "revision.json"}
                or asset.startswith(".") or ".." in Path(asset).parts):
            abort(404)
        return send_from_directory(state / "current", asset)

    @pages.get("/calendar/calendar-config.json")
    def calendar_config():
        return jsonify(api=True)

    # FullCalendar injects its own stylesheet and sets element style attributes.
    # Limit the host CSP relaxation to calendar documents, never account pages.
    @pages.after_request
    def calendar_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
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
