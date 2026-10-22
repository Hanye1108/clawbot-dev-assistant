"""笔记：先存本地数据库；配置了 Memos 就同时发一份到你自己的 Memos（失败不影响本地保存）。"""
import logging

import requests

from . import config
from .db import insert, now_iso, run

log = logging.getLogger(__name__)


def memos_enabled():
    return bool(config.MEMOS_URL and config.MEMOS_TOKEN)


def push_memos(content):
    """Memos v0.22 及以后的接口：POST /api/v1/memos。成功返回 True。"""
    r = requests.post(f"{config.MEMOS_URL}/api/v1/memos",
                      json={"content": content, "visibility": "PRIVATE"},
                      headers={"Authorization": f"Bearer {config.MEMOS_TOKEN}"}, timeout=10)
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:100]}")
    return True


def add(content, source="chat"):
    content = (content or "").strip()
    if not content:
        return "内容是空的"
    synced = 0
    msg = "已存进笔记"
    if memos_enabled():
        try:
            push_memos(content + "\n\n#开发助手")
            synced = 1
            msg = "已存进笔记，并同步到 Memos"
        except Exception as e:  # noqa: BLE001
            log.warning("同步 Memos 失败：%s", e)
            msg = f"已存进本地笔记（同步 Memos 失败：{str(e)[:60]}）"
    nid = insert("INSERT INTO notes (content, source, synced, ts) VALUES (?,?,?,?)",
                 (content, source, synced, now_iso()))
    return f"{msg}（#{nid}）"


def recent(n=10, keyword=""):
    if keyword:
        rows = run("SELECT id, content, ts FROM notes WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                   (f"%{keyword}%", n), fetch=True)
    else:
        rows = run("SELECT id, content, ts FROM notes ORDER BY id DESC LIMIT ?", (n,), fetch=True)
    return [{"编号": r["id"], "时间": r["ts"][:16].replace("T", " "), "内容": r["content"]} for r in rows]


def delete(nid):
    run("DELETE FROM notes WHERE id=?", (nid,))
