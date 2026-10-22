import datetime

from devbot import db


class FakeChannel:
    def __init__(self, owner="me@im.wechat", in_window=True):
        self.sent = []
        self.owner = owner
        self.in_window = in_window

    def owner_uid(self):
        return self.owner

    def send_text(self, uid, text):
        if not self.in_window:
            return False
        self.sent.append(text)
        return True

    def push_deadline(self, uid):
        return db.now() + datetime.timedelta(hours=10 if self.in_window else -1)

    def status_lines(self):
        return ["fake channel"]


def reset_db():
    db.init_db()
    for t in ("chat", "kv", "pending", "reports", "seen_repos", "notes"):
        db.run(f"DELETE FROM {t}")
