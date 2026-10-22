"""命令行入口（都在项目目录里，用 .venv/bin/python -m devbot ... 运行）

  python -m devbot            启动机器人（systemd 服务用的就是这个）
  python -m devbot setup      配置向导：填密钥 → 检查 → 扫码绑定微信 → 启动
  python -m devbot check      检查配置和外部服务
  python -m devbot login      扫码绑定你自己的微信 ClawBot
  python -m devbot report     生成今天的热榜并打印出来（不发微信，用来测试）
"""
import argparse
import logging
import sys

from . import __version__, config

REQUIRED_MODULES = {"openai": "openai", "requests": "requests", "apscheduler": "apscheduler", "qrcode": "qrcode"}
INSTALL_HINT = ".venv/bin/pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"


def missing_packages():
    import importlib.util
    return [pkg for pkg, mod in REQUIRED_MODULES.items() if importlib.util.find_spec(mod) is None]


def cmd_run():
    if missing_packages():
        raise SystemExit(f"缺少依赖：{', '.join(missing_packages())}。请运行：{INSTALL_HINT}")
    missing = config.missing_settings()
    if missing:
        raise SystemExit(f"缺少配置：{', '.join(missing)}。运行 .venv/bin/python -m devbot setup 填写")
    from .core import Bot, start_scheduler
    from .db import init_db
    from .ilink import IlinkChannel
    init_db()
    bot = Bot()
    bot.channel = IlinkChannel(bot)
    start_scheduler(bot)
    logging.getLogger(__name__).info("clawbot-dev-assistant %s 已启动，每天 %s 推送热榜", __version__, config.REPORT_TIME)
    bot.channel.run()


def cmd_check():
    ok = True

    def show(good, name, hint=""):
        nonlocal ok
        ok = ok and good
        print(("✅ " if good else "❌ ") + name + ("" if good else f"\n   → {hint}"))

    print(f"clawbot-dev-assistant {__version__}，数据目录 {config.DATA_DIR}\n")
    pk = missing_packages()
    show(not pk, "Python 依赖齐全", f"缺少 {', '.join(pk)}，运行：{INSTALL_HINT}")
    if pk:
        return 1
    for name in config.missing_settings():
        show(False, f"配置项 {name}", "在 .env 里填写，或运行 setup 向导")
    from .db import init_db, kv_get, kv_set
    init_db()
    kv_set("check", "1")
    show(kv_get("check") == "1", f"数据库可写（{config.DB_PATH}）")

    if config.DEEPSEEK_KEY:
        try:
            from .llm import client, opts
            r = client().chat.completions.create(model=config.MODEL, max_tokens=10, timeout=30, **opts(),
                                                 messages=[{"role": "user", "content": "回复OK"}])
            show(bool(r.choices), f"DeepSeek 对话（{config.MODEL}，实际响应 {getattr(r, 'model', '?')}）")
        except Exception as e:  # noqa: BLE001
            show(False, f"DeepSeek 对话（{config.MODEL}）", f"{e}\n   检查 Key、余额和模型名")
        try:
            from .llm import get_balance
            bal = get_balance()
            show(bal["available"], f"DeepSeek 余额：{bal['total']} {bal['currency']}", "余额不足，去充值")
        except Exception as e:  # noqa: BLE001
            show(False, "DeepSeek 余额查询", str(e))

    from . import github
    try:
        items = github.trending("", "daily")
        show(bool(items), f"GitHub Trending 页面（解析到 {len(items)} 个项目）", "页面结构可能变了")
    except github.GithubError as e:
        show(False, "GitHub Trending 页面", f"{e}\n   国内服务器偶尔连不上 GitHub，过会儿再试；每天推送时会自动重试")
    try:
        github.search_repos("esp32 in:topics stars:>1000", per_page=1)
        show(True, "GitHub 搜索 API" + ("（已配置 Token）" if config.GITHUB_TOKEN else "（未配置 Token，额度较低但够用）"))
    except github.GithubError as e:
        show(False, "GitHub 搜索 API", str(e))

    from . import notes
    if notes.memos_enabled():
        import requests
        try:
            r = requests.get(f"{config.MEMOS_URL}/api/v1/memos", params={"pageSize": 1},
                             headers={"Authorization": f"Bearer {config.MEMOS_TOKEN}"}, timeout=10)
            show(r.status_code == 200, "Memos 连接", f"HTTP {r.status_code}：检查 MEMOS_URL 和 MEMOS_TOKEN")
        except Exception as e:  # noqa: BLE001
            show(False, "Memos 连接", str(e))

    from . import sysinfo
    for svc in config.WATCH_SERVICES:
        print(f"ℹ️  看门狗监视 {svc}：当前 {sysinfo.service_state(svc)}")

    from .ilink import load_accounts
    accs = load_accounts()
    show(bool(accs), f"已绑定 ClawBot：{', '.join(a['_name'] for a in accs) or '无'}",
         "运行 .venv/bin/python -m devbot login 扫码绑定")
    try:
        import requests
        requests.get(config.ILINK_BASE_URL, timeout=10)
        show(True, "能访问微信 iLink 服务器")
    except Exception as e:  # noqa: BLE001
        show(False, "能访问微信 iLink 服务器", str(e))
    print("\n全部通过 🎉" if ok else "\n还有问题需要处理")
    return 0 if ok else 1


def cmd_report(save):
    from . import report
    from .db import init_db
    init_db()
    rep = report.build(save=save)
    for text in rep["messages"]:
        print(text)
        print("\n" + "=" * 40 + "\n")
    print(f"（共 {len(rep['items'])} 个项目；{'已保存，可在微信里用「展开/收藏」' if save else '没有保存'}）")
    return 0


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="python -m devbot", description="clawbot-dev-assistant")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="启动机器人（默认）")
    sub.add_parser("setup", help="配置向导")
    sub.add_parser("check", help="检查配置和外部服务")
    lp = sub.add_parser("login", help="扫码绑定微信 ClawBot")
    lp.add_argument("name", nargs="?", default="me")
    rp = sub.add_parser("report", help="生成今天的热榜并打印（不发微信）")
    rp.add_argument("--save", action="store_true", help="保存到数据库（微信里可以展开/收藏）")
    a = p.parse_args(argv)
    if a.cmd == "setup":
        from .setup_wizard import main as setup_main
        return setup_main()
    if a.cmd == "check":
        return cmd_check()
    if a.cmd == "login":
        from .ilink import login
        return login(a.name)
    if a.cmd == "report":
        return cmd_report(a.save)
    cmd_run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
