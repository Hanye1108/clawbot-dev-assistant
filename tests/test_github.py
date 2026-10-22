from pathlib import Path

from devbot import github

FIX = Path(__file__).parent / "fixtures" / "trending.html"


def test_parse_trending():
    items = github.parse_trending(FIX.read_text())
    assert [i["repo"] for i in items] == ["cloudflare/security-audit-skill", "vllm-project/vllm",
                                         "Graphify-Labs/graphify", "someone/no-desc-repo"]
    first = items[0]
    assert first["stars"] == 36631 and first["today"] == 2012 and first["lang"] == "JavaScript"
    assert "security audits" in first["desc"]
    assert items[2]["desc"].endswith("& more.")          # HTML 实体被还原
    assert items[3]["desc"] == "" and items[3]["lang"] == ""


def test_parse_repo_ref():
    assert github.parse_repo_ref("https://github.com/vllm-project/vllm.git") == "vllm-project/vllm"
    assert github.parse_repo_ref("https://github.com/a/b/tree/main/src") == "a/b"
    assert github.parse_repo_ref("owner/repo") == "owner/repo"
    assert github.parse_repo_ref("随便说说") is None


def test_clean_readme():
    md = "# T\n\n[![ci](https://x/badge.svg)](https://x)\n![logo](a.png)\n<p align=center><img src=x></p>\n\n\n\nhello  world"
    out = github.clean_readme(md, 100)
    assert "badge" not in out and "<img" not in out and "hello world" in out
