"""Serialize Git writes; stage complete releases before atomically switching readers."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_feeds import build_site, load_source_events, serialize_event  # noqa: E402

ZONE = ZoneInfo("Asia/Shanghai")
FIELDS = {"title", "location", "description", "sourceUrl", "scope", "status",
          "start", "end", "alarmMode", "alarmMinutes", "version"}


class PublicationError(Exception):
    pass


class RetryPublication(Exception):
    """The remote outcome is unknown; retain the same job id and reconcile later."""


def validate_payload(payload, operation):
    if not isinstance(payload, dict) or set(payload) - FIELDS:
        raise ValueError("包含不支持的日历字段。")
    if operation != "add" and (not isinstance(payload.get("version"), str)
                               or len(payload["version"]) != 64):
        raise ValueError("缺少事件版本，请刷新后重试。")
    if operation == "delete":
        if set(payload) != {"version"}:
            raise ValueError("删除请求只接受事件版本。")
        return
    if operation == "add" and not {"title", "scope", "start", "end"} <= payload.keys():
        raise ValueError("请填写标题、范围和开始及结束时间。")
    if not payload.keys() - {"version"}:
        raise ValueError("没有需要保存的变更。")
    for key, limit in (("title", 600), ("location", 600), ("description", 12000),
                       ("sourceUrl", 2000), ("start", 40), ("end", 40)):
        if key in payload and (not isinstance(payload[key], str) or len(payload[key]) > limit
                               or "\x00" in payload[key]):
            raise ValueError(f"字段格式无效：{key}")
    for key in ("title", "location"):
        if key in payload and (payload[key] or key == "title"):
            parts = payload[key].split(" / ", 1)
            if len(parts) != 2 or not all(part.strip() for part in parts):
                raise ValueError("标题和地点须填写中文 / English。")
    for key, allowed in (("scope", ("public", "internal")), ("status", ("planned", "tentative")),
                         ("alarmMode", ("keep", "clear", "set"))):
        if key in payload and payload[key] not in allowed:
            raise ValueError(f"字段选项无效：{key}")
    if payload.get("alarmMode") == "set":
        value = payload.get("alarmMinutes")
        if type(value) is not int or not 0 <= value <= 525600:
            raise ValueError("提醒分钟数无效。")
    elif "alarmMinutes" in payload:
        raise ValueError("请同时选择设置提醒。")
    if payload.get("sourceUrl"):
        parts = urlsplit(payload["sourceUrl"])
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("来源链接必须是 HTTP 或 HTTPS 地址。")
    for key in ("start", "end"):
        if key in payload:
            try:
                datetime.fromisoformat(payload[key])
            except ValueError as exc:
                raise ValueError("时间格式无效。") from exc


def snapshot(root):
    result = []
    for entries in load_source_events(root).values():
        for entry in entries:
            data = serialize_event(entry, root)
            data["version"] = hashlib.sha256(
                entry.path.relative_to(root).as_posix().encode() + b"\0" + entry.path.read_bytes()
            ).hexdigest()
            data["path"] = entry.path.relative_to(root).as_posix()
            data["recurring"] = any(name in entry.event for name in ("RRULE", "RDATE", "EXDATE"))
            data["alarms"] = [
                str(alarm.get("TRIGGER", "").to_ical().decode())
                for alarm in entry.event.subcomponents
                if alarm.name == "VALARM" and alarm.get("TRIGGER") is not None
            ]
            result.append(data)
    return sorted(result, key=lambda event: event["start"])


def run(args, cwd=None, *, timeout=60, env=None):
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise PublicationError("操作超时，请稍后重试。") from exc
    if result.returncode:
        # CLI validation errors are safe; Git stderr can contain credential URLs.
        if len(args) > 1 and args[1] == str(ROOT / "scripts/calendar_cli.py"):
            raise PublicationError(result.stderr.strip()[:800])
        raise PublicationError("Git 同步或推送失败；未确认发布，请稍后重试。")
    return result.stdout.strip()


class Publisher:
    def __init__(self, state, remote, store, branch="main", can_manage=None):
        self.state = Path(state)
        self.state.mkdir(parents=True, exist_ok=True)
        self.remote = remote
        self.branch = branch
        self.store = store
        self.can_manage = can_manage or (
            lambda user_id: self.store.role(user_id) in ("admin", "editor")
        )
        self.env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_AUTHOR_NAME="BETA Calendar",
                        GIT_AUTHOR_EMAIL="calendar@betasdc.invalid",
                        GIT_COMMITTER_NAME="BETA Calendar", GIT_COMMITTER_EMAIL="calendar@betasdc.invalid")

    @contextmanager
    def lock(self):
        with (self.state / "publish.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    @contextmanager
    def checkout(self):
        with tempfile.TemporaryDirectory(prefix="calendar-", dir=self.state) as temp:
            root = Path(temp) / "repo"
            run(["git", "clone", "--quiet", "--single-branch", "--branch", self.branch,
                 "--", self.remote, str(root)], env=self.env)
            yield root

    def cli(self, root, *args):
        text = run([sys.executable, str(ROOT / "scripts/calendar_cli.py"), "--root", str(root), *args, "-j"])
        return json.loads(text)

    def stage(self, root, commit):
        releases = self.state / "releases"
        releases.mkdir(exist_ok=True)
        # Include code revision so a UI upgrade also rebuilds an unchanged event commit.
        code_hash = hashlib.sha256()
        for path in sorted((ROOT / "web").rglob("*")):
            if path.is_file():
                code_hash.update(path.relative_to(ROOT).as_posix().encode())
                code_hash.update(path.read_bytes())
        name = f"{commit}-{code_hash.hexdigest()[:12]}"
        release = releases / name
        if not release.exists():
            with tempfile.TemporaryDirectory(prefix="build-", dir=self.state) as temp:
                output = Path(temp) / "site"
                build_site(root, output, ROOT / "web")
                (output / "server-events.json").write_text(
                    json.dumps({"events": snapshot(root)}, ensure_ascii=False), encoding="utf-8")
                (output / "revision.json").write_text(json.dumps({"commit": commit}), encoding="utf-8")
                output.rename(release)
        return release

    def activate(self, release):
        target = self.state / "current.next"
        target.unlink(missing_ok=True)
        target.symlink_to(release.relative_to(self.state), target_is_directory=True)
        os.replace(target, self.state / "current")

    def sync(self):
        with self.lock(), self.checkout() as root:
            commit = run(["git", "rev-parse", "HEAD"], cwd=root)
            self.activate(self.stage(root, commit))

    def apply(self, root, job):
        payload = json.loads(job["payload"])
        validate_payload(payload, job["operation"])
        existing = next((event for event in snapshot(root) if event["uid"] == job["uid"]), None)
        if job["operation"] != "add":
            if existing is None or existing["version"] != payload["version"]:
                raise PublicationError("事件已被修改或删除，请刷新日历后重新编辑。")
            if existing["recurring"] and job["operation"] != "delete":
                raise PublicationError("重复活动请通过日历 CLI 维护。")
        if job["operation"] == "delete":
            self.cli(root, "delete", job["uid"], "--yes")
            return
        args = ["add" if job["operation"] == "add" else "update"]
        if job["operation"] == "add":
            args.extend(["--uid", job["uid"]])
        else:
            args.append(job["uid"])
        options = {"title": "--title", "location": "--location", "scope": "--scope",
                   "status": "--status", "start": "--start", "end": "--end",
                   "description": "--description", "sourceUrl": "--url"}
        for key, option in options.items():
            if key in payload:
                # --option=value prevents user text from becoming a CLI option.
                args.append(f"{option}={payload[key]}")
        if payload.get("alarmMode") == "clear":
            if job["operation"] != "add":
                args.append("--clear-alarms")
        elif payload.get("alarmMode") == "set":
            args.append(f"--alarm-minutes={payload['alarmMinutes']}")
        self.cli(root, *args)

    def process(self, job):
        with self.lock(), self.checkout() as root:
            # Reconcile a crash after push: never apply an accepted change twice.
            matched = run(["git", "log", "--format=%H", "--fixed-strings",
                           f"--grep=Calendar-Job: {job['id']}", "-1"], cwd=root)
            if matched:
                head = run(["git", "rev-parse", "HEAD"], cwd=root)
                self.activate(self.stage(root, head))
                self.store.finish(job["id"], "succeeded", matched)
                return
            if not self.can_manage(job["user_id"]):
                raise PublicationError("编辑权限已被撤销。")
            self.store.finish(job["id"], "running")
            self.apply(root, job)
            self.cli(root, "validate")
            # A complete, validated build must exist before anything reaches GitHub.
            with tempfile.TemporaryDirectory(dir=self.state) as temp:
                build_site(root, Path(temp) / "site", ROOT / "web")
            run(["git", "add", "--", "public", "internal"], cwd=root)
            message = (f"calendar: {job['operation']} {job['uid']}\n\n"
                       f"Calendar-Actor: {job['user_id']}\nCalendar-Job: {job['id']}")
            run(["git", "commit", "--allow-empty", "-m", message], cwd=root, env=self.env)
            commit = run(["git", "rev-parse", "HEAD"], cwd=root)
            staged = self.stage(root, commit)
            try:
                run(["git", "push", "origin", f"HEAD:refs/heads/{self.branch}"], cwd=root, env=self.env)
            except PublicationError:
                try:
                    run(["git", "fetch", "origin", self.branch], cwd=root, env=self.env)
                except PublicationError as exc:
                    raise RetryPublication("无法确认推送结果，将使用相同请求自动核对。") from exc
                found = run(["git", "log", "FETCH_HEAD", "--format=%H", "--fixed-strings",
                             f"--grep=Calendar-Job: {job['id']}", "-1"], cwd=root)
                if not found:
                    raise PublicationError("远端冲突或推送失败，未发布本次更改。")
                # Other writers may have advanced the branch after our successful push.
                run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=root)
                staged = self.stage(root, run(["git", "rev-parse", "HEAD"], cwd=root))
            self.activate(staged)
            self.store.finish(job["id"], "succeeded", commit)
