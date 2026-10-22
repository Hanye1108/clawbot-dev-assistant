"""DeepSeek 调用（OpenAI 兼容接口）：带工具的对话、一次性生成、要求返回 JSON 的生成。"""
import json
import logging
import re
import time

from . import config

log = logging.getLogger(__name__)
_client = None
MAX_TOOL_ROUNDS = 6


def opts():
    if config.DEEPSEEK_THINKING in ("enabled", "disabled"):
        return {"extra_body": {"thinking": {"type": config.DEEPSEEK_THINKING}}}
    return {}


def client():
    global _client
    if _client is None:
        from openai import OpenAI  # 延迟导入，单元测试不需要装 openai
        _client = OpenAI(api_key=config.DEEPSEEK_KEY, base_url=config.DEEPSEEK_BASE_URL)
    return _client


def get_balance():
    import requests
    r = requests.get(config.DEEPSEEK_BASE_URL + "/user/balance",
                     headers={"Authorization": f"Bearer {config.DEEPSEEK_KEY}"}, timeout=10)
    r.raise_for_status()
    data = r.json()
    infos = data.get("balance_infos") or [{}]
    info = next((i for i in infos if i.get("currency") == "CNY"), infos[0])
    return {"available": bool(data.get("is_available")),
            "total": info.get("total_balance", "?"), "currency": info.get("currency", "")}


def chat(messages, tools, run_tool, fallback="我查得有点久，换个说法再问一次？"):
    """多轮工具调用，直到模型给出最终文字回复。"""
    messages = list(messages)
    start = time.monotonic()
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            resp = client().chat.completions.create(
                model=config.MODEL, messages=messages, tools=tools, timeout=90, **opts())
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return (msg.content or "").strip() or fallback
            messages.append(msg)
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except ValueError:
                    args = {}
                log.info("调用工具 %s %s", call.function.name, json.dumps(args, ensure_ascii=False)[:120])
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": run_tool(call.function.name, args)})
        return fallback
    finally:
        log.info("回复耗时 %.1fs", time.monotonic() - start)


def write(system, user, timeout=120):
    resp = client().chat.completions.create(
        model=config.MODEL, timeout=timeout, **opts(),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return (resp.choices[0].message.content or "").strip()


def extract_json(raw):
    """从模型回复里取出 JSON（允许它包在 ```json 代码块里或前后有多余文字）。"""
    raw = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.S)
    if m:
        raw = m.group(1).strip()
    for open_, close in (("[", "]"), ("{", "}")):
        s, e = raw.find(open_), raw.rfind(close)
        if s != -1 and e > s:
            try:
                return json.loads(raw[s:e + 1])
            except ValueError:
                continue
    raise ValueError("模型没有返回合法的 JSON：" + raw[:200])


def write_json(system, user, timeout=150):
    return extract_json(write(system, user, timeout))
