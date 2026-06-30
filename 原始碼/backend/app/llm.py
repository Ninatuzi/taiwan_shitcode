"""模型调用层 — Task 6。

经 OpenAI 兼容接口（本地 vLLM）流式调用模型。
端点 / 模型名 / 上下文 / 输出上限全部读配置，切换只改 .env 不改代码。
"""
from __future__ import annotations

import re
from collections.abc import Iterator

from openai import OpenAI

from .config import get_settings

_settings = get_settings()


def get_client() -> OpenAI:
    # vLLM 通常不校验 key，但 openai 客户端要求非空，给个占位。
    return OpenAI(
        base_url=_settings.llm_base_url,
        api_key=_settings.llm_api_key or "sk-noauth",
        timeout=_settings.llm_timeout,
    )


def stream_chat(prompt: str) -> Iterator[str]:
    """流式调用模型，逐段产出文本增量。Task 7 的 SSE 也复用本函数。"""
    client = get_client()
    stream = client.chat.completions.create(
        model=_settings.llm_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=_settings.llm_max_output_tokens,
        temperature=0.3,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


_FENCE_RE = re.compile(r"^\s*```(?:html)?\s*|\s*```\s*$", re.IGNORECASE)

# 控制字符（保留 \t \n \r），含会让 PostgreSQL 报错的 NUL(0x00)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# 推理模型(DeepSeek-R1 等)的思考段
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)


def clean_output(text: str) -> str:
    """清洗模型输出：去 NUL/控制字符、剥离 <think> 思考段与 ```html 围栏。

    - NUL(0x00) 会导致 PostgreSQL text 字段入库报错，必须去掉。
    - DeepSeek-R1 等推理模型会先输出 <think>…</think>，只保留之后的正文。
    """
    if not text:
        return ""
    # 1) 去除 NUL 与其它控制字符
    text = _CTRL_RE.sub("", text)
    # 2) 剥离成对的 <think>…</think>
    text = _THINK_RE.sub("", text)
    # 3) 剥离未闭合的 <think>（思考被输出上限截断，没有 </think>）——从 <think> 起全部丢弃
    text = _THINK_OPEN_RE.sub("", text)
    # 4) 剥离 ```html 围栏
    text = re.sub(r"^\s*```(?:html)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?\s*```\s*$", "", text)
    return text.strip()


def strip_html_fences(text: str) -> str:
    """向后兼容：等价于 clean_output。"""
    return clean_output(text)
