"""SQLite：一个文件存全部数据（data/devbot.db），和健康助手的数据库互不相干。"""
import datetime
import json
import os
import sqlite3
from contextlib import closing

from . import config

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, role TEXT, content TEXT, ts TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_chat ON chat(user_id, id)",
    "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)",
    """CREATE TABLE IF NOT EXISTS pending (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, text TEXT, ts TEXT, expires_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS ilink_sessions (
        account_id TEXT, user_id TEXT, context_token TEXT, updated_at TEXT,
        PRIMARY KEY (account_id, user_id))""",
    # 每天一份热榜：items 是带编号的项目列表（JSON），用于「展开 3」「收藏 3」
    """CREATE TABLE IF NOT EXISTS reports (
        day TEXT PRIMARY KEY, items TEXT, messages TEXT, created_at TEXT, sent_at TEXT)""",
    # 推荐过的仓库：热榜统计上榜天数，嵌入式精选不重复推荐
    """CREATE TABLE IF NOT EXISTS seen_repos (
        repo TEXT, kind TEXT, first_day TEXT, last_day TEXT, times INTEGER,
        PRIMARY KEY (repo, kind))""",
    """CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT, source TEXT, synced INTEGER, ts TEXT)""",
]


def run(sql, args=(), fetch=False):
    with closing(sqlite3.connect(str(config.DB_PATH), timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, args)
        rows = cur.fetchall() if fetch else None
        conn.commit()
        return rows


def insert(sql, args=()):
    with closing(sqlite3.connect(str(config.DB_PATH), timeout=10)) as conn:
        cur = conn.execute(sql, args)
        conn.commit()
        return cur.lastrowid


def init_db():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for sql in SCHEMA:
        run(sql)
    try:
        os.chmod(config.DB_PATH, 0o600)
    except OSError:
        pass


def kv_get(key, default=None):
    rows = run("SELECT value FROM kv WHERE key=?", (key,), fetch=True)
    return rows[0]["value"] if rows else default


def kv_set(key, value):
    run("INSERT INTO kv (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def kv_json(key, default):
    try:
        return json.loads(kv_get(key) or "null") or default
    except ValueError:
        return default


def now():
    return datetime.datetime.now(config.TZ)


def now_iso():
    return now().isoformat()


def today_str():
    return now().strftime("%Y-%m-%d")


# ---------- 聊天历史 ----------
def add_chat(uid, role, content):
    run("INSERT INTO chat (user_id, role, content, ts) VALUES (?,?,?,?)", (uid, role, content, now_iso()))
    run("DELETE FROM chat WHERE user_id=? AND id NOT IN "
        "(SELECT id FROM chat WHERE user_id=? ORDER BY id DESC LIMIT 200)", (uid, uid))


def load_history(uid, n=16):
    rows = run("SELECT role, content FROM chat WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, n), fetch=True)
    msgs = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def clear_chat(uid):
    run("DELETE FROM chat WHERE user_id=?", (uid,))


# ---------- 推送不出去时暂存，等你下次说话补发 ----------
def add_pending(uid, text, keep_hours):
    run("DELETE FROM pending WHERE expires_at < ?", (now_iso(),))
    expires = (now() + datetime.timedelta(hours=keep_hours)).isoformat()
    run("INSERT INTO pending (user_id, text, ts, expires_at) VALUES (?,?,?,?)", (uid, text, now_iso(), expires))


def take_pending(uid):
    rows = run("SELECT text FROM pending WHERE user_id=? AND expires_at >= ? ORDER BY id",
               (uid, now_iso()), fetch=True)
    run("DELETE FROM pending WHERE user_id=?", (uid,))
    return [r["text"] for r in rows]
