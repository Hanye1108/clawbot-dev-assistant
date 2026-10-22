from devbot import core, db, github, llm, notes, report
from tests.helpers import FakeChannel, reset_db
from tests.test_report import setup as setup_report

UID = "me@im.wechat"


def make_bot(**kw):
    bot = core.Bot()
    bot.channel = FakeChannel(**kw)
    return bot


def test_first_greeting_shows_help(monkeypatch):
    reset_db()
    bot = make_bot()
    called = []
    monkeypatch.setattr(llm, "chat", lambda *a, **k: called.append(1) or "hi")
    bot.handle_text(UID, "你好")
    assert "GitHub 热榜" in bot.channel.sent[0] and not called
    bot.handle_text(UID, "STM32 的 CAN 波特率怎么算")
    assert bot.channel.sent[-1] == "hi" and called


def test_report_command_and_expand_collect(monkeypatch):
    setup_report(monkeypatch)
    db.kv_set("intro", core.INTRO_VERSION)
    bot = make_bot()
    bot.handle_text(UID, "热榜")
    assert any(m.startswith("📈 GitHub 热榜") for m in bot.channel.sent)
    assert report.load()["sent_at"]
    monkeypatch.setattr(report, "expand", lambda repo: "详细介绍内容")
    bot.handle_text(UID, "展开 2")
    assert "📖 o/r11" in bot.channel.sent[-1] and "详细介绍内容" in bot.channel.sent[-1]
    bot.handle_text(UID, "收藏 11")
    assert "已存进笔记" in bot.channel.sent[-1] and "z/zephyr-board" in bot.channel.sent[-1]
    assert "z/zephyr-board" in notes.recent()[0]["内容"]
    bot.handle_text(UID, "展开 50")
    assert "没有第 50 个" in bot.channel.sent[-1]


def test_scheduled_report_outside_window_is_queued(monkeypatch):
    setup_report(monkeypatch)
    db.kv_set("intro", core.INTRO_VERSION)
    bot = make_bot(in_window=False)
    core.report_job(bot)
    assert bot.channel.sent == []
    assert db.kv_get(f"report_done:{db.today_str()}")
    core.report_job(bot)                                   # 不会重复生成/暂存
    assert len(db.run("SELECT * FROM pending", fetch=True)) == 2
    bot.channel.in_window = True
    bot.handle_text(UID, "热榜")                          # 补发的就是热榜，不再重复发
    assert len(bot.channel.sent) == 2 and "今早的热榜" in bot.channel.sent[0]


def test_scheduled_report_hint_when_window_closing(monkeypatch):
    setup_report(monkeypatch)
    bot = make_bot()
    core.report_job(bot)
    assert "明早的热榜才能按时送到" in bot.channel.sent[-1]


def test_report_retry_on_github_failure(monkeypatch):
    setup_report(monkeypatch)
    bot = make_bot()
    monkeypatch.setattr(github, "trending", lambda *a, **k: (_ for _ in ()).throw(github.GithubError("timeout")))
    jobs = []

    class FakeSched:
        def add_job(self, fn, trigger, args, run_date):
            jobs.append(args)
    monkeypatch.setattr(core, "_scheduler", FakeSched())
    core.report_job(bot)
    assert jobs and jobs[0][1] == 2
    core.report_job(bot, attempt=4)
    assert "热榜没取到" in bot.channel.sent[-1]


def test_interest_commands():
    reset_db()
    db.kv_set("intro", core.INTRO_VERSION)
    bot = make_bot()
    bot.handle_text(UID, "关注 RK3588")
    assert "RK3588" in report.interests()
    bot.handle_text(UID, "取消关注 stm32")
    assert "STM32" not in report.interests()


def test_watchdog_transitions(monkeypatch):
    reset_db()
    bot = make_bot()
    states = iter(["active", "failed", "failed", "active"])
    monkeypatch.setattr(core.config, "WATCH_SERVICES", ["clawbot-health-buddy"])
    monkeypatch.setattr(core.sysinfo, "service_state", lambda s: next(states))
    monkeypatch.setattr(core.sysinfo, "journal_has", lambda *a, **k: False)
    monkeypatch.setattr(core.sysinfo, "disk", lambda p="/": {"使用率%": 50, "可用GB": 10})
    for _ in range(4):
        core.watchdog_job(bot)
    sent = bot.channel.sent
    assert len(sent) == 2 and "停了" in sent[0] and "恢复运行" in sent[1]


def test_notes_memos_failure_still_saves(monkeypatch):
    reset_db()
    monkeypatch.setattr(notes.config, "MEMOS_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(notes.config, "MEMOS_TOKEN", "t")
    res = notes.add("记一下：RK3506 CAN 时钟要先开")
    assert "本地笔记" in res and notes.recent()[0]["内容"].startswith("记一下")
