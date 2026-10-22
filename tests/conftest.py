import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="devbot-test-")
os.environ["ENV_FILE"] = os.path.join(_tmp, "none.env")   # 不读真实 .env
os.environ["DATA_DIR"] = _tmp
os.environ["DEEPSEEK_KEY"] = "sk-test"
os.environ["WATCH_SERVICES"] = ""
os.environ["GITHUB_TOKEN"] = "x"     # 让嵌入式搜索不 sleep
