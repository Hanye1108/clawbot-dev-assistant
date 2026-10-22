"""不装 pytest 也能跑测试：python3 tests/run_tests.py（装了 pytest 的话直接 pytest -q 也行）。"""
import importlib
import inspect
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import tests.conftest  # noqa: E402,F401  设置测试用的环境变量

_MISSING = object()


class MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        old = getattr(target, name, _MISSING)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            if old is _MISSING:
                delattr(target, name)
            else:
                setattr(target, name, old)
        self._undo.clear()


def main():
    passed, failed = 0, []
    for path in sorted(HERE.glob("test_*.py")):
        mod = importlib.import_module(f"tests.{path.stem}")
        for name, fn in inspect.getmembers(mod, inspect.isfunction):
            if not name.startswith("test_") or fn.__module__ != mod.__name__:
                continue
            mp = MonkeyPatch()
            try:
                fn(mp) if "monkeypatch" in inspect.signature(fn).parameters else fn()
                passed += 1
            except Exception:  # noqa: BLE001
                failed.append(f"{path.stem}.{name}\n{traceback.format_exc()}")
            finally:
                mp.undo()
    for f in failed:
        print("FAIL", f)
    print(f"{passed} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
