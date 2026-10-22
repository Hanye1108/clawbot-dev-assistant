"""配置向导：.venv/bin/python -m devbot setup

填密钥（输入不显示）→ 自动检查 → 扫码绑定你的微信 → 启动服务。可以重复运行，已填的项直接回车保留。
"""
import getpass
import os
import re
import shutil
import subprocess
import sys

from . import config

# (配置名, 说明, 隐藏输入, 必填)
ITEMS = [
    ("DEEPSEEK_KEY", "DeepSeek API Key（sk- 开头；建议单独建一个 Key，方便分开看用量）", True, True),
    ("REPORT_TIME", "每天几点推送热榜（24 小时制，如 07:40；建议 9 点前）", False, False),
    ("GITHUB_TOKEN", "GitHub Token（可选，直接回车跳过；不填每小时 60 次额度，够用）", True, False),
    ("MEMOS_URL", "Memos 地址（可选，如 http://127.0.0.1:5230，不用就回车）", False, False),
    ("MEMOS_TOKEN", "Memos Access Token（可选，Memos 设置 → 我的账号 → Access Tokens）", True, False),
]


def read_env(path):
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
            if m:
                values[m.group(1)] = m.group(2).strip().strip("'\"")
    return values


def write_env(path, updates):
    if not path.is_file():
        example = config.ROOT / ".env.example"
        shutil.copy(example, path) if example.is_file() else path.write_text("", encoding="utf-8")
    lines = path.read_text(encoding="utf-8").splitlines()
    done = set()
    for i, line in enumerate(lines):
        m = re.match(r"\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=", line)
        if m and m.group(1) in updates and m.group(1) not in done:
            lines[i] = f"{m.group(1)}={updates[m.group(1)]}"
            done.add(m.group(1))
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def mask(v):
    return v[:4] + "****" + v[-4:] if len(v) > 10 else "****"


def clean(name, value):
    value = value.strip().strip("'\"")
    if re.search(r"\s", value):
        return None, "中间不能有空格"
    if name == "REPORT_TIME" and value:
        m = re.fullmatch(r"(\d{1,2})[:：](\d{2})", value)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            return None, "格式是 时:分，比如 07:40"
        value = f"{int(m.group(1)):02d}:{m.group(2)}"
    if name == "MEMOS_URL" and value:
        if not value.startswith(("http://", "https://")):
            value = "http://" + value
        value = value.rstrip("/")
    if name == "DEEPSEEK_KEY" and not value.startswith("sk-"):
        return value, "DeepSeek 的 Key 一般以 sk- 开头，确认没复制错？（仍会保存）"
    return value, None


def yes(prompt, default=True):
    ans = input(prompt + (" [Y/n] " if default else " [y/N] ")).strip().lower()
    return default if not ans else ans in ("y", "yes", "是", "好")


def run_self(*args):
    return subprocess.call([sys.executable, "-m", "devbot", *args], cwd=str(config.ROOT))


def health_buddy_accounts():
    folder = config.HEALTH_BUDDY_DIR / "data" / "ilink"
    try:
        return sorted(p.stem for p in folder.glob("*.json"))
    except OSError:
        return []


def main():
    if not sys.stdin.isatty():
        print("setup 需要在终端里交互运行。也可以直接编辑 .env，见 README.md")
        return 1
    path = config.ROOT / ".env"
    current = read_env(path)
    print("\n=== clawbot-dev-assistant 配置向导 ===")
    print(f"配置文件：{path}\n已经填过的项直接回车保留。密钥输入时屏幕上不显示，粘贴后回车即可。\n")

    updates = {}
    hb_key = read_env(config.HEALTH_BUDDY_DIR / ".env").get("DEEPSEEK_KEY", "")
    if not current.get("DEEPSEEK_KEY") and hb_key:
        if yes(f"检测到健康助手的 DeepSeek Key（{mask(hb_key)}），直接复用吗？（选否就输入一个新的）", default=False):
            updates["DEEPSEEK_KEY"] = hb_key
    for name, desc, hidden, required in ITEMS:
        if name in updates:
            continue
        old = current.get(name, "")
        while True:
            shown = f"（当前：{mask(old) if hidden else old}）" if old else ""
            print(f"· {desc}{shown}")
            value = (getpass.getpass("  请输入：") if hidden else input("  请输入：")).strip()
            if not value:
                if old or not required:
                    break
                print("  这一项必填。")
                continue
            value, err = clean(name, value)
            if value is None:
                print(f"  ❌ {err}")
                continue
            if err:
                print(f"  ⚠️  {err}")
            updates[name] = value
            break
    if updates:
        write_env(path, updates)
        print(f"\n✅ 已保存 {len(updates)} 项到 .env（权限 600）")

    print("\n=== 检查配置 ===")
    run_self("check")

    from .ilink import load_accounts
    print("\n=== 绑定微信 ===")
    mine = [a["_name"] for a in load_accounts()]
    if mine:
        print(f"本项目已绑定：{', '.join(mine)}")
    else:
        hb = health_buddy_accounts()
        if hb:
            print(f"ℹ️  健康助手（{config.HEALTH_BUDDY_DIR}）里绑定了这些账号：{', '.join(hb)}")
            print("   如果其中某个（通常是 me）就是你自己的微信，建议先让健康助手放开它，避免两个程序抢同一个微信的消息：")
            print(f"     mv {config.HEALTH_BUDDY_DIR}/data/ilink/me.json {config.HEALTH_BUDDY_DIR}/data/ilink/me.json.bak")
            print("     systemctl restart clawbot-health-buddy")
            print("   你女朋友那边不受影响；健康助手只是少了给你发告警的通道，")
            print("   本项目的看门狗会盯着它的服务状态和登录过期日志，替你接住告警。想恢复把 .bak 改回来即可。")
        if yes("现在用你自己的微信扫码绑定吗？"):
            run_self("login", "me")

    if shutil.which("systemctl") and os.geteuid() == 0:
        print("\n=== 启动服务 ===")
        if yes(f"现在（重新）启动 {config.SERVICE} 吗？"):
            subprocess.call(["systemctl", "restart", config.SERVICE])
            subprocess.call(["systemctl", "--no-pager", "--lines=5", "status", config.SERVICE])
            print("\n🎉 好了！在微信里找到 ClawBot，发「你好」看功能介绍，发「热榜」立刻看今天的。")
    else:
        print(f"\n用 root 运行 systemctl restart {config.SERVICE} 启动服务。")
    return 0
