"""嵌入向量 — Task 11。经 OpenAI 兼容接口调用本地嵌入模型(如 BGE-M3)。

嵌入模型不可用时 embed_text 返回 None,检索自动降级为关键词检索。
"""
from __future__ import annotations

import html as _html
import re

from openai import OpenAI

from .config import get_settings

_settings = get_settings()
_TAG_RE = re.compile(r"<[^>]+>")


def _client() -> OpenAI:
    return OpenAI(
        base_url=_settings.embed_base_url,
        api_key=_settings.llm_api_key or "sk-noauth",
        timeout=30,
    )


def embed_text(text: str) -> list[float] | None:
    """生成嵌入向量;失败(模型不可用/网络等)返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    try:
        resp = _client().embeddings.create(model=_settings.embed_model, input=text[:8000])
        return list(resp.data[0].embedding)
    except Exception:
        return None


def html_to_text(html: str) -> str:
    """把结果 HTML 转成可嵌入/检索的纯文本。"""
    return _html.unescape(_TAG_RE.sub(" ", html or "")).strip()
