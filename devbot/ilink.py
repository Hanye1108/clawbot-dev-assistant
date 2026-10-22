"""微信 ClawBot 通道（腾讯 iLink Bot 协议），从 clawbot-health-buddy 精简而来（只收发文字和语音转文字）。

- 扫码登录得到 bot_token，所有请求带 Bearer token。
- POST ilink/bot/getupdates 长轮询收消息，get_updates_buf 游标增量拉取。
- POST ilink/bot/sendmessage 发消息，必须带上对方最近一条消息里的 context_token。
- 对方约 24 小时没说话后，微信就不让主动推送了（发送接口不一定报错，但收不到）。
"""
import base64
import datetime
import json
import logging
import os
import random
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

from . import config
from .db import kv_get, kv_set, now, now_iso, run

log = logging.getLogger(__name__)
CHANNEL_VERSION = "1.0.2"
TEXT_LIMIT = 1000


def _headers(token):
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": base64.b64encode(str(random.randint(0, 0xFFFFFFFF)).encode()).decode(),
    }


def _norm(user_id):
    return (user_id or "").split("@")[0]


def split_text(text, size=TEXT_LIMIT):
    """按行切成不超过 size 的几段，尽量不把一个项目拆到两条消息里（空行处优先断开）。"""
    text = (text or "").strip()
    if len(text) <= size:
        return [text]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        piece = block if not cur else cur + "\n\n" + block
        if len(piece) <= size:
            cur = piece
            continue
        if cur:
            parts.append(cur)
            cur = ""
        while len(block) > size:          # 单个段落太长，只能按行/硬切
            cut = block.rfind("\n", 0, size)
            cut = cut if cut > size // 2 else size
            parts.append(block[:cut])
            block = block[cut:].lstrip("\n")
        cur = block
    if cur:
        parts.append(cur)
    return parts


def load_accounts():
    accounts = []
    folder = config.ILINK_ACCOUNTS_DIR
    if not folder.is_dir():
        return accounts
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            log.error("账号文件损坏：%s", path)
            continue
        if data.get("bot_token"):
            data["_name"] = path.stem
            accounts.append(data)
    return accounts


class Account:
    def __init__(self, data, bot):
        self.name = data["_name"]
        self.token = data["bot_token"]
        self.base = (data.get("baseurl") or config.ILINK_BASE_URL).rstrip("/")
        self.bot_id = data.get("ilink_bot_id") or self.name
        self.owner = data.get("ilink_user_id", "")
        self.bot = bot
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"ilink-{self.name}")
        self.seen = []
        self.tickets = {}

    def post(self, path, body, timeout=15):
        raw = json.dumps({**body, "base_info": {"channel_version": CHANNEL_VERSION}},
                         ensure_ascii=False).encode("utf-8")
        r = requests.post(f"{self.base}/{path}", data=raw, headers=_headers(self.token), timeout=timeout)
        r.raise_for_status()
        return r.json() if r.text.strip() else {}

    def send(self, uid, text, context_token):
        for part in split_text(text):
            resp = self.post("ilink/bot/sendmessage", {"msg": {
                "from_user_id": "", "to_user_id": uid,
                "client_id": f"cda-{uuid.uuid4().hex[:16]}",
                "message_type": 2, "message_state": 2,
                "context_token": context_token,
                "item_list": [{"type": 1, "text_item": {"text": part}}]}})
            if resp.get("ret") not in (None, 0) or resp.get("errcode") not in (None, 0):
                log.warning("[%s] 发送失败：%s", self.name, resp)
                return False
        return True

    # ---------- "对方正在输入…" ----------
    def typing(self, uid, context_token, on):
        try:
            cached = self.tickets.get(uid)
            if cached and time.time() - cached[1] < 12 * 3600:
                ticket = cached[0]
            else:
                ticket = self.post("ilink/bot/getconfig",
                                   {"ilink_user_id": uid, "context_token": context_token}).get("typing_ticket")
                if ticket:
                    self.tickets[uid] = (ticket, time.time())
            if ticket:
                self.post("ilink/bot/sendtyping",
                          {"ilink_user_id": uid, "typing_ticket": ticket, "status": 1 if on else 2}, timeout=5)
        except Exception as e:  # noqa: BLE001
            log.debug("[%s] 输入状态发送失败：%s", self.name, e)

    def poll_forever(self):
        key = f"ilink_cursor:{self.bot_id}"
        buf = kv_get(key, "")
        fails = 0
        log.info("[%s] 开始接收消息", self.name)
        while True:
            try:
                resp = self.post("ilink/bot/getupdates", {"get_updates_buf": buf}, timeout=45)
            except requests.exceptions.ReadTimeout:
                continue
            except Exception as e:  # noqa: BLE001
                fails += 1
                log.warning("[%s] 拉取消息出错（第%d次）：%s", self.name, fails, e)
                time.sleep(30 if fails >= 3 else 5)
                continue
            code = resp.get("errcode") or resp.get("ret") or 0
            if code == -14:
                log.error("[%s] 登录已过期，需要重新扫码：cd %s && .venv/bin/python -m devbot login %s",
                          self.name, config.ROOT, self.name)
                time.sleep(300)
                continue
            if code:
                fails += 1
                log.warning("[%s] 接口返回错误：%s", self.name,
                            {k: v for k, v in resp.items() if k not in ("msgs", "get_updates_buf")})
                time.sleep(30 if fails >= 3 else 5)
                continue
            fails = 0
            if resp.get("get_updates_buf"):
                buf = resp["get_updates_buf"]
                kv_set(key, buf)
            for msg in resp.get("msgs") or []:
                self.dispatch(msg)

    def dispatch(self, msg):
        if msg.get("message_type") != 1:
            return
        mid = msg.get("message_id") or msg.get("client_id")
        if mid:
            if mid in self.seen:
                return
            self.seen = (self.seen + [mid])[-300:]
        uid = msg.get("from_user_id") or ""
        if config.ILINK_ONLY_OWNER and self.owner and _norm(uid) != _norm(self.owner):
            log.warning("[%s] 忽略非扫码人的消息（确认是本人的话在 .env 设 ILINK_ONLY_OWNER=0）", self.name)
            return
        ctx = msg.get("context_token") or ""
        if ctx:
            run("INSERT INTO ilink_sessions (account_id, user_id, context_token, updated_at) "
                "VALUES (?,?,?,?) ON CONFLICT(account_id, user_id) DO UPDATE SET "
                "context_token=excluded.context_token, updated_at=excluded.updated_at",
                (self.bot_id, uid, ctx, now_iso()))
        self.worker.submit(self._handle, uid, msg.get("item_list") or [], ctx)

    def _handle(self, uid, items, ctx=""):
        stop = threading.Event()
        if ctx:
            def keep_typing():
                while not stop.is_set():
                    self.typing(uid, ctx, True)
                    stop.wait(5)
            threading.Thread(target=keep_typing, daemon=True).start()
        try:
            texts = []
            for it in items:
                if it.get("type") == 1 and it.get("text_item"):
                    texts.append(it["text_item"].get("text", ""))
                elif it.get("type") == 3 and (it.get("voice_item") or {}).get("text"):
                    texts.append(it["voice_item"]["text"])   # 语音自带转文字
            if any(s.strip() for s in texts):
                self.bot.handle_text(uid, "\n".join(texts))
            else:
                self.bot.send(uid, "目前只看得懂文字和语音，图片和文件还不支持。")
        except Exception:  # noqa: BLE001
            log.exception("[%s] 处理消息出错", self.name)
        finally:
            stop.set()
            if ctx:
                self.typing(uid, ctx, False)


class IlinkChannel:
    def __init__(self, bot):
        self.bot = bot
        self.accounts = {}
        for data in load_accounts():
            acc = Account(data, bot)
            self.accounts[acc.bot_id] = acc

    def _session(self, uid=None):
        if uid:
            rows = run("SELECT * FROM ilink_sessions WHERE user_id=? ORDER BY updated_at DESC LIMIT 1",
                       (uid,), fetch=True)
        else:
            rows = run("SELECT * FROM ilink_sessions ORDER BY updated_at DESC LIMIT 1", fetch=True)
        return dict(rows[0]) if rows else {}

    def owner_uid(self):
        """推送对象：扫码绑定的人（就是你）。账号文件里没有的话，用最近给机器人发过消息的人。"""
        for acc in self.accounts.values():
            if acc.owner:
                return acc.owner
        return self._session().get("user_id")

    def last_seen(self, uid):
        s = self._session(uid)
        return datetime.datetime.fromisoformat(s["updated_at"]) if s.get("updated_at") else None

    def push_deadline(self, uid):
        last = self.last_seen(uid)
        return last + datetime.timedelta(hours=config.ILINK_PUSH_WINDOW_HOURS) if last else None

    def send_text(self, uid, text):
        s = self._session(uid)
        acc = self.accounts.get(s.get("account_id"))
        ctx = s.get("context_token")
        if not acc or not ctx:
            log.warning("还没有会话令牌，无法发送（先在微信里给 ClawBot 发一条消息）")
            return False
        deadline = self.push_deadline(uid)
        if deadline and now() > deadline:
            log.info("距你上次发消息已超过 %s 小时，微信不允许主动发送，先暂存", config.ILINK_PUSH_WINDOW_HOURS)
            return False
        try:
            return acc.send(uid, text, ctx)
        except Exception as e:  # noqa: BLE001
            log.warning("[%s] 发送异常：%s", acc.name, e)
            return False

    def status_lines(self):
        lines = []
        for acc in self.accounts.values():
            rows = run("SELECT updated_at FROM ilink_sessions WHERE account_id=? ORDER BY updated_at DESC LIMIT 1",
                       (acc.bot_id,), fetch=True)
            if not rows:
                lines.append(f"ClawBot「{acc.name}」：还没收到过消息")
                continue
            hours = (now() - datetime.datetime.fromisoformat(rows[0]["updated_at"])).total_seconds() / 3600
            left = config.ILINK_PUSH_WINDOW_HOURS - hours
            lines.append(f"ClawBot「{acc.name}」：{hours:.1f} 小时前收到你的消息，"
                         + (f"还能主动推送 {left:.1f} 小时" if left > 0 else "已过推送窗口"))
        return lines

    def run(self):
        if not self.accounts:
            raise SystemExit("没有找到 ClawBot 账号。请先运行：.venv/bin/python -m devbot login")
        threads = []
        for acc in self.accounts.values():
            t = threading.Thread(target=acc.poll_forever, name=f"poll-{acc.name}", daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()


def login(name="me"):
    """扫码登录 ClawBot，凭据保存到 data/ilink/<name>.json（本项目自己的目录）。"""
    folder = config.ILINK_ACCOUNTS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    path = folder / f"{name}.json"

    r = requests.get(f"{config.ILINK_BASE_URL}/ilink/bot/get_bot_qrcode", params={"bot_type": 3}, timeout=15).json()
    code = r["qrcode"]
    content = r.get("qrcode_img_content") or code
    try:
        import qrcode
        q = qrcode.QRCode(border=1)
        q.add_data(content)
        q.make()
        q.print_ascii(invert=True)
    except ImportError:
        print("（没装 qrcode，无法在终端画二维码）")
    print("\n用你自己的微信扫上面的二维码并确认。")
    print("终端二维码扫不出来时，把这个链接转成二维码再扫：", content)

    deadline = time.time() + 480
    while time.time() < deadline:
        try:
            s = requests.get(f"{config.ILINK_BASE_URL}/ilink/bot/get_qrcode_status",
                             params={"qrcode": code}, headers={"iLink-App-ClientVersion": "1"}, timeout=40).json()
        except requests.exceptions.RequestException:
            time.sleep(2)
            continue
        status = s.get("status")
        if status == "confirmed":
            s["saved_at"] = int(time.time())
            path.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
            os.chmod(path, 0o600)
            print(f"\n✅ 登录成功，已保存到 {path}")
            print(f"下一步：systemctl restart {config.SERVICE}，然后在微信里给 ClawBot 发一句「你好」。")
            return 0
        if status == "expired":
            print("二维码过期了，请重新运行")
            return 1
        time.sleep(1)
    print("超时了，请重新运行")
    return 1
