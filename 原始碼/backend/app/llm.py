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


def strip_html_fences(text: str) -> str:
    """剥离模型可能输出的 ```html 围栏与前后多余空白。"""
    text = text.strip()
    # 去掉开头的 ```html / ``` 和结尾的 ```
    text = re.sub(r"^\s*```(?:html)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?\s*```\s*$", "", text)
    return text.strip()
