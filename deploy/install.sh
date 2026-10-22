#!/usr/bin/env bash
# =====================================================================
# 一键安装 clawbot-dev-assistant
#
# 用法（在项目目录里，用 root）：
#   bash deploy/install.sh --mirror   # 国内服务器推荐：用清华 pip 镜像
#   bash deploy/install.sh            # 官方 pip 源，失败自动换清华镜像
#
# 和同一台机器上的 clawbot-health-buddy 互不影响：
#   - 独立目录（默认 /opt/clawbot-dev-assistant）、独立虚拟环境、独立数据库
#   - 独立服务名 clawbot-dev-assistant；Python 包名 devbot（健康助手是 bot）
#   - 不监听任何端口，不改 OpenResty / Docker / 1Panel 的任何配置
# 可以重复运行：不会覆盖已填写的 .env 和已有数据。
# =====================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE=clawbot-dev-assistant
MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
USE_MIRROR=0
for arg in "$@"; do
  case "$arg" in
    --mirror) USE_MIRROR=1 ;;
    *) echo "未知参数：$arg"; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 运行：sudo bash deploy/install.sh"
  exit 1
fi

MEM_MB="$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
echo "==> 安装目录 $APP_DIR，架构 $(uname -m)，内存 ${MEM_MB}MB"

echo "==> [1/6] 安装系统依赖"
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip ca-certificates cron tzdata
  systemctl enable --now cron >/dev/null 2>&1 || true
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y python3 python3-pip cronie ca-certificates
  systemctl enable --now crond >/dev/null 2>&1 || true
elif command -v yum >/dev/null 2>&1; then
  yum install -y python3 python3-pip cronie ca-certificates
  systemctl enable --now crond >/dev/null 2>&1 || true
else
  echo "    未识别的包管理器，请确保已安装 Python 3.8+ 和 venv"
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || {
  echo "需要 Python 3.8 或更高版本，当前是 $(python3 --version)"; exit 1; }

echo "==> [2/6] 检查和健康助手是否冲突"
if [[ "$APP_DIR" == "/opt/clawbot-health-buddy" ]]; then
  echo "❌ 不能装在健康助手的目录里，请把本项目放到 /opt/clawbot-dev-assistant"
  exit 1
fi
if systemctl cat clawbot-health-buddy >/dev/null 2>&1; then
  echo "    发现 clawbot-health-buddy 服务：本项目不会动它，只会在它停掉时提醒你"
else
  echo "    没有发现健康助手服务，跳过"
fi

echo "==> [3/6] 创建虚拟环境并安装 Python 依赖"
python3 -m venv "$APP_DIR/.venv"
PIP="$APP_DIR/.venv/bin/pip"
pip_install() {
  if [[ $USE_MIRROR == 1 ]]; then
    "$PIP" install --prefer-binary -i "$MIRROR" "$@"
  else
    "$PIP" install --prefer-binary "$@" || {
      echo "    官方源安装失败，换清华镜像重试……"
      "$PIP" install --prefer-binary -i "$MIRROR" "$@"
    }
  fi
}
pip_install --upgrade pip -q
pip_install -r "$APP_DIR/requirements.txt"

echo "==> [4/6] 准备配置文件和数据目录"
mkdir -p "$APP_DIR/data/ilink" "$APP_DIR/data/backup"
chmod 700 "$APP_DIR/data" "$APP_DIR/data/ilink" "$APP_DIR/data/backup"
if [[ ! -f "$APP_DIR/.env" ]]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "    已生成 .env（下一步用 setup 向导填写）"
else
  echo "    .env 已存在，保留原内容"
fi
chmod 600 "$APP_DIR/.env"

echo "==> [5/6] 安装开机自启服务 $SERVICE"
sed "s#__APP_DIR__#$APP_DIR#g" "$APP_DIR/deploy/$SERVICE.service" > "/etc/systemd/system/$SERVICE.service"
systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null 2>&1
if systemctl is-active --quiet "$SERVICE"; then
  systemctl restart "$SERVICE"
  echo "    服务已在运行，已重启以加载新代码"
else
  echo "    已设为开机自启（暂未启动，填好配置并绑定微信后再启动）"
fi

echo "==> [6/6] 每天 04:20 自动备份数据库"
chmod +x "$APP_DIR/deploy/backup.sh"
if command -v crontab >/dev/null 2>&1; then
  ( crontab -l 2>/dev/null | grep -v "$APP_DIR/deploy/backup.sh" || true
    echo "20 4 * * * bash $APP_DIR/deploy/backup.sh >/dev/null 2>&1" ) | crontab -
  echo "    已加入 crontab"
else
  echo "    没有 crontab 命令，跳过自动备份"
fi

cat <<EOT

✅ 安装完成。下一步运行这一条，跟着提示走（填 Key → 检查 → 扫码绑定你的微信 → 启动）：

    cd $APP_DIR && .venv/bin/python -m devbot setup

常用命令：
    systemctl status $SERVICE              # 运行状态
    journalctl -u $SERVICE -f              # 实时日志
    .venv/bin/python -m devbot report      # 现场生成一次热榜打印出来（不发微信）
EOT
