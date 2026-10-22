"""配置：优先读取环境变量，其次读取项目根目录下的 .env 文件。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICE = "clawbot-dev-assistant"


def _load_env_file():
    path = Path(os.environ.get("ENV_FILE") or ROOT / ".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env_file()

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python 3.8
    from backports.zoneinfo import ZoneInfo


def env(name, default=""):
    return os.environ.get(name, default).strip()


def env_list(name, default):
    raw = env(name) or default
    return [x.strip() for x in raw.replace("，", ",").split(",") if x.strip()]


def env_int(name, default):
    try:
        return int(env(name, str(default)) or default)
    except ValueError:
        return default


BOT_NAME = env("BOT_NAME", "小码")

# DeepSeek
DEEPSEEK_KEY = env("DEEPSEEK_KEY")
DEEPSEEK_BASE_URL = env("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = env("DEEPSEEK_MODEL", "deepseek-flash")
# 思考模式：disabled 关闭（快，推荐）、enabled 开启、留空不传
DEEPSEEK_THINKING = env("DEEPSEEK_THINKING", "disabled").lower()
SEARCH_ENABLED = env("SEARCH_ENABLED", "1") == "1"
ALERT_BALANCE = float(env("ALERT_BALANCE", "5") or 5)

# GitHub
GITHUB_TOKEN = env("GITHUB_TOKEN")          # 可选：填了以后 API 额度从每小时 60 次提高到 5000 次
REPORT_TIME = env("REPORT_TIME", "07:40")   # 每天几点推送热榜
TOP_N = env_int("TOP_N", 10)
EMBEDDED_N = env_int("EMBEDDED_N", 3)
EMBEDDED_LANGS = env_list("EMBEDDED_LANGS", "c,c++,rust,assembly")
EMBEDDED_TOPICS = env_list(
    "EMBEDDED_TOPICS",
    "embedded,firmware,microcontroller,rtos,zephyr,esp32,stm32,rp2040,riscv,kicad,pcb,"
    "linux-kernel,device-driver,can-bus,fpga")
INTERESTS = env_list(
    "INTERESTS", "Rockchip,RK3506,RV1126,ESP32,STM32,Zephyr,RTOS,CAN,MIPI CSI,Linux驱动,KiCad,嘉立创EDA")

# Memos（可选）：收藏和笔记同步到你自己的 Memos
MEMOS_URL = env("MEMOS_URL").rstrip("/")
MEMOS_TOKEN = env("MEMOS_TOKEN")

# 服务器看门狗：这些 systemd 服务停了就提醒你（逗号分隔，留空关闭）
WATCH_SERVICES = env_list("WATCH_SERVICES", "clawbot-health-buddy") if env("WATCH_SERVICES", "x") else []
DISK_ALERT_PERCENT = env_int("DISK_ALERT_PERCENT", 90)

# 时区与数据目录
TZ = ZoneInfo(env("BOT_TIMEZONE", "Asia/Shanghai"))
DATA_DIR = Path(env("DATA_DIR") or ROOT / "data")
DB_PATH = Path(env("DB_PATH") or DATA_DIR / "devbot.db")

# 微信 ClawBot（iLink）
ILINK_BASE_URL = env("ILINK_BASE_URL", "https://ilinkai.weixin.qq.com").rstrip("/")
ILINK_ACCOUNTS_DIR = DATA_DIR / "ilink"
ILINK_ONLY_OWNER = env("ILINK_ONLY_OWNER", "1") == "1"
# 对方最后一次发消息约 24 小时后微信就不让主动推送了，默认 23 小时留余量
ILINK_PUSH_WINDOW_HOURS = float(env("ILINK_PUSH_WINDOW_HOURS", "23") or 23)

# 同一台服务器上的健康助手，只用来提示可能的冲突，不会去改它
HEALTH_BUDDY_DIR = Path(env("HEALTH_BUDDY_DIR") or "/opt/clawbot-health-buddy")

REQUIRED = ["DEEPSEEK_KEY"]


def missing_settings():
    return [n for n in REQUIRED if not env(n)]


def report_hour_minute():
    try:
        h, m = REPORT_TIME.split(":")
        return int(h), int(m)
    except ValueError:
        return 7, 40
