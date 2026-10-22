"""从 GitHub 取数据：Trending 页面、仓库搜索、仓库信息和 README。

GitHub 没有官方的 Trending API，这里解析 github.com/trending 的网页。
国内服务器连 GitHub 经常抖动，所有请求都带超时和重试；取不到时抛 GithubError，由调用方决定怎么处理。
"""
import base64
import datetime
import html
import logging
import re
import time

import requests

from . import config

log = logging.getLogger(__name__)
WEB = "https://github.com"
API = "https://api.github.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) clawbot-dev-assistant"


class GithubError(Exception):
    pass


def _get(url, params=None, api=False, raw=False, tries=3, timeout=20):
    headers = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if api:
        headers["Accept"] = "application/vnd.github.raw" if raw else "application/vnd.github+json"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        if config.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 404:
                raise GithubError("not found")
            if r.status_code in (403, 429) and api:
                left = r.headers.get("X-RateLimit-Remaining")
                raise GithubError(f"GitHub API 额度用完了（剩余 {left}），可以在 .env 里填 GITHUB_TOKEN 提高额度")
            r.raise_for_status()
            return r
        except GithubError:
            raise
        except requests.RequestException as e:
            last = e
            log.warning("请求 GitHub 失败（第 %d 次）：%s %s", i + 1, url, e)
            if i + 1 < tries:
                time.sleep(3 * (i + 1))
    raise GithubError(f"连不上 GitHub：{type(last).__name__}: {str(last)[:120]}")


# ---------- Trending ----------
def _num(s):
    return int(re.sub(r"[^\d]", "", s or "0") or 0)


def _text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_trending(page):
    """解析 trending 页面，返回 [{repo, desc, lang, stars, today}]，保持页面上的顺序。"""
    page = re.sub(r"<svg\b[^>]*/>|<svg\b.*?</svg>", "", page, flags=re.S)
    out = []
    for art in re.findall(r'<article class="Box-row"[^>]*>(.*?)</article>', page, flags=re.S):
        h2 = re.search(r"<h2\b.*?</h2>", art, flags=re.S)
        m = re.search(r'href="/([^/"?#\s]+/[^/"?#\s]+)"', h2.group(0)) if h2 else None
        if not m:
            continue
        repo = m.group(1)
        desc = re.search(r"<p\b[^>]*>(.*?)</p>", art, flags=re.S)
        lang = re.search(r'itemprop="programmingLanguage"[^>]*>(.*?)<', art, flags=re.S)
        stars = re.search(r'href="/%s/stargazers"[^>]*>(.*?)</a>' % re.escape(repo), art, flags=re.S)
        today = re.search(r"([\d,]+)\s+stars?\s+(?:today|this week|this month)", art)
        out.append({
            "repo": repo,
            "desc": _text(desc.group(1)) if desc else "",
            "lang": _text(lang.group(1)) if lang else "",
            "stars": _num(_text(stars.group(1))) if stars else 0,
            "today": _num(today.group(1)) if today else 0,
        })
    return out


def trending(language="", since="daily"):
    """language 留空是全部语言；since: daily / weekly / monthly。"""
    lang = language.strip().lower().replace("c++", "c%2B%2B").replace("#", "%23").replace(" ", "-")
    url = f"{WEB}/trending" + (f"/{lang}" if lang else "")
    page = _get(url, params={"since": since}).text
    items = parse_trending(page)
    if not items and "Box-row" not in page:
        raise GithubError("Trending 页面解析不到项目（可能 GitHub 改版了，或者返回了验证页面）")
    return items


# ---------- 搜索 ----------
def search_repos(query, per_page=20, sort="stars"):
    r = _get(f"{API}/search/repositories", params={"q": query, "sort": sort, "order": "desc",
                                                   "per_page": per_page}, api=True)
    out = []
    for it in r.json().get("items") or []:
        out.append({
            "repo": it.get("full_name", ""),
            "desc": (it.get("description") or "").strip(),
            "lang": it.get("language") or "",
            "stars": it.get("stargazers_count") or 0,
            "topics": (it.get("topics") or [])[:8],
            "created": (it.get("created_at") or "")[:10],
            "pushed": (it.get("pushed_at") or "")[:10],
        })
    return out


def embedded_search(topics, days=45, min_stars=15):
    """最近一段时间新建、和嵌入式相关的仓库（按 star 排序）。
    GitHub 搜索的 OR 最多 5 个，所以分组查；没填 GITHUB_TOKEN 时搜索每分钟限 10 次，组间稍等一下。"""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    groups = [topics[i:i + 5] for i in range(0, len(topics), 5)]
    out, seen = [], set()
    for gi, group in enumerate(groups):
        q = " OR ".join(group) + f" in:topics,name,description created:>={since} stars:>={min_stars}"
        try:
            items = search_repos(q, per_page=20)
        except GithubError as e:
            log.warning("嵌入式搜索失败（%s）：%s", group, e)
            continue
        for it in items:
            if it["repo"] not in seen:
                seen.add(it["repo"])
                it["source"] = "新项目搜索"
                out.append(it)
        if gi + 1 < len(groups) and not config.GITHUB_TOKEN:
            time.sleep(7)
    return out


# ---------- 单个仓库 ----------
def parse_repo_ref(text):
    """从 'owner/repo'、GitHub 链接等写法里提取 owner/repo。"""
    text = (text or "").strip()
    m = re.search(r"github\.com/([\w.-]+)/([\w.-]+)", text)
    if not m:
        m = re.fullmatch(r"([\w.-]+)/([\w.-]+)", text)
    if not m:
        return None
    repo = m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{m.group(1)}/{repo}"


def repo_info(repo):
    it = _get(f"{API}/repos/{repo}", api=True).json()
    return {
        "repo": it.get("full_name", repo),
        "desc": it.get("description") or "",
        "lang": it.get("language") or "",
        "stars": it.get("stargazers_count") or 0,
        "forks": it.get("forks_count") or 0,
        "topics": it.get("topics") or [],
        "license": (it.get("license") or {}).get("spdx_id") or "",
        "created": (it.get("created_at") or "")[:10],
        "pushed": (it.get("pushed_at") or "")[:10],
        "homepage": it.get("homepage") or "",
        "archived": bool(it.get("archived")),
    }


def clean_readme(text, limit):
    """去掉 HTML、图片和徽章，压缩空白，截断到 limit 个字符。"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)                 # 图片/徽章
    text = re.sub(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)", "", text)
    text = re.sub(r"<img\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:limit]


def readme(repo, limit=3000):
    try:
        r = _get(f"{API}/repos/{repo}/readme", api=True, raw=True, tries=2)
    except GithubError as e:
        if "not found" in str(e):
            return ""
        raise
    body = r.text
    if r.headers.get("Content-Type", "").startswith("application/json"):   # 个别代理不认 raw
        try:
            body = base64.b64decode(r.json().get("content", "")).decode("utf-8", "replace")
        except ValueError:
            pass
    return clean_readme(body, limit)
