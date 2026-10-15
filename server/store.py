"""Roles, durable publication requests, and audit history."""
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
import uuid


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS roles (
                    user_id INTEGER PRIMARY KEY, username TEXT NOT NULL, role TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, username TEXT NOT NULL,
                    operation TEXT NOT NULL, uid TEXT, payload TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', error TEXT,
                    commit_sha TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, username TEXT NOT NULL,
                    operation TEXT NOT NULL, details TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def role(self, user_id):
        with self.connection() as db:
            row = db.execute("SELECT role FROM roles WHERE user_id=?", (user_id,)).fetchone()
            return row["role"] if row else "viewer"

    def roles(self):
        with self.connection() as db:
            return [{"userId": row["user_id"], "username": row["username"], "role": row["role"]}
                    for row in db.execute("SELECT * FROM roles ORDER BY user_id")]

    def grant(self, actor, account, role):
        if role not in ("viewer", "editor", "admin"):
            raise ValueError("无效角色。")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT role FROM roles WHERE user_id=?", (account["id"],)).fetchone()
            if current and current["role"] == "admin" and role != "admin":
                if db.execute("SELECT COUNT(*) FROM roles WHERE role='admin'").fetchone()[0] <= 1:
                    raise ValueError("不能撤销最后一位管理员。")
            db.execute("INSERT INTO roles VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                       "username=excluded.username,role=excluded.role",
                       (account["id"], account["username"], role))
            db.execute("INSERT INTO audit(user_id,username,operation,details) VALUES(?,?,?,?)",
                       (actor["id"], actor["username"], "grant",
                        json.dumps({"userId": account["id"], "role": role})))

    def enqueue(self, actor, operation, uid, payload, job_id=None):
        job_id = job_id or uuid.uuid4().hex
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if existing:
                if (existing["user_id"] == actor["id"] and existing["operation"] == operation
                        and existing["uid"] == uid and json.loads(existing["payload"]) == payload):
                    return job_id
                raise ValueError("发布请求编号已使用。")
            if db.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND state IN ('pending','running')",
                          (actor["id"],)).fetchone()[0] >= 5:
                raise ValueError("已有多项更改等待发布，请稍后重试。")
            db.execute("INSERT INTO jobs(id,user_id,username,operation,uid,payload) VALUES(?,?,?,?,?,?)",
                       (job_id, actor["id"], actor["username"], operation, uid,
                        json.dumps(payload, ensure_ascii=False)))
        return job_id

    def job(self, job_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    def next_job(self):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE state IN ('pending','running') "
                             "ORDER BY created_at,id LIMIT 1").fetchone()
            return dict(row) if row else None

    def finish(self, job_id, state, commit=None, error=None):
        with self.connection() as db:
            db.execute("UPDATE jobs SET state=?,commit_sha=?,error=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                       (state, commit, error, job_id))
            if state in ("succeeded", "failed"):
                job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
                db.execute("INSERT INTO audit(user_id,username,operation,details) VALUES(?,?,?,?)",
                           (job["user_id"], job["username"], job["operation"],
                            json.dumps({"job": job_id, "uid": job["uid"], "state": state,
                                        "commit": commit, "error": error})))
