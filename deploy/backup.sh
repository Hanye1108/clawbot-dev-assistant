#!/usr/bin/env bash
# 备份数据库：按星期几命名，保留最近 7 份。install.sh 会把它加入每天 04:20 的定时任务。
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
SRC="$DATA_DIR/devbot.db"
DST_DIR="$DATA_DIR/backup"
[[ -f "$SRC" ]] || { echo "没有数据库：$SRC"; exit 0; }
mkdir -p "$DST_DIR"
DST="$DST_DIR/devbot-$(date +%u).db"
"$APP_DIR/.venv/bin/python" - "$SRC" "$DST" <<'PY'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PY
chmod 600 "$DST"
echo "已备份到 $DST"
