import json

from devbot import github, llm, report
from tests.helpers import reset_db

TREND = [{"repo": f"o/r{i}", "desc": f"desc {i}", "lang": "Python", "stars": 1000 * i, "today": 10 * i}
         for i in range(1, 13)]
C_TREND = [{"repo": "esp/idf-thing", "desc": "ESP32 thing", "lang": "C", "stars": 300, "today": 30}]
SEARCH = [{"repo": "z/zephyr-board", "desc": "Zephyr board", "lang": "C", "stars": 120, "topics": ["zephyr"]},
          {"repo": "g/game-port", "desc": "game", "lang": "C++", "stars": 900, "topics": ["firmware"]}]


def fake_trending(language="", since="daily"):
    return [dict(x) for x in (TREND if not language else C_TREND if language == "c" else [])]


def fake_write_json(system, user):
    data = json.loads(user)
    if "嵌入式工程师从候选项目" in system:
        names = {d["名称"]: d["n"] for d in data}
        return [{"n": names["z/zephyr-board"], "简介": "Zephyr 开发板支持", "推荐理由": "和你关注的 Zephyr 相关"},
                {"n": 999, "简介": "越界的编号应被忽略"}]
    return [{"n": d["n"], "简介": f"中文简介{d['n']}", "看点": f"看点{d['n']}", "嵌入式相关": d["n"] == 2}
            for d in data]


def setup(monkeypatch, write_json=fake_write_json):
    reset_db()
    monkeypatch.setattr(github, "trending", fake_trending)
    monkeypatch.setattr(github, "readme", lambda repo, limit=3000: "readme of " + repo)
    monkeypatch.setattr(github, "embedded_search", lambda topics: [dict(x) for x in SEARCH])
    monkeypatch.setattr(llm, "write_json", write_json)


def test_build_report(monkeypatch):
    setup(monkeypatch)
    rep = report.build("2026-10-22")
    top = rep["items"][:10]
    assert [it["repo"] for it in top] == [f"o/r{i}" for i in range(12, 2, -1)]   # 按今日新增排序取前 10
    assert rep["items"][10]["repo"] == "z/zephyr-board" and len(rep["items"]) == 11
    msg = rep["messages"]
    assert len(msg) == 2
    assert msg[0].startswith("📈 GitHub 热榜 · 10月22日")
    assert "1. o/r12" in msg[0] and "⭐+120（总 12.0k）" in msg[0] and "中文简介1" in msg[0]
    assert "🔧 嵌入式精选" in msg[1] and "11. z/zephyr-board" in msg[1] and "展开 3" in msg[1]
    assert report.item(11)["repo"] == "z/zephyr-board"
    assert report.item(99) is None


def test_embedded_not_repeated_and_streak(monkeypatch):
    setup(monkeypatch)
    report.build("2026-10-21")
    rep = report.build("2026-10-22")
    assert all(it["repo"] != "z/zephyr-board" for it in rep["items"])    # 推荐过的不再推荐
    assert "🔁第2次上榜" in rep["messages"][0]
    rep2 = report.build("2026-10-22")                                       # 同一天重复生成不重复计数
    assert "🔁第3次上榜" not in rep2["messages"][0]


def test_llm_down_falls_back(monkeypatch):
    def broken(system, user):
        raise RuntimeError("down")
    setup(monkeypatch, broken)
    rep = report.build("2026-10-22")
    assert "DeepSeek 没响应" in rep["messages"][0] and "desc 12" in rep["messages"][0]
    assert len(rep["messages"]) == 1 and "展开 3" in rep["messages"][0]


def test_github_down(monkeypatch):
    setup(monkeypatch)

    def down(language="", since="daily"):
        raise github.GithubError("连不上 GitHub")
    monkeypatch.setattr(github, "trending", down)
    try:
        report.build("2026-10-22")
        assert False
    except report.ReportError as e:
        assert "连不上" in str(e)


def test_extract_json():
    assert llm.extract_json('```json\n[{"n": 1}]\n```') == [{"n": 1}]
    assert llm.extract_json('好的：[{"n": 2}] 以上') == [{"n": 2}]
