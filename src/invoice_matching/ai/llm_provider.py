"""LLM Provider 接口：OpenAI-Compatible Chat Completions，避免绑定单一厂商。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests

from ..config import settings
from ..logging_config import get_logger

log = get_logger(__name__)


class LlmError(RuntimeError):
    """LLM 调用或解析失败。"""


class LlmProvider(Protocol):
    def chat(self, messages: list[dict], temperature: float = 0.0) -> str: ...


@dataclass
class OpenAiCompatibleProvider:
    base_url: str
    api_key: str
    model: str
    timeout: int = 60

    def chat(self, messages: list[dict], temperature: float = 0.0) -> str:
        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise LlmError(f"LLM 请求失败：{exc}") from exc
        if resp.status_code != 200:
            raise LlmError(f"LLM 返回 {resp.status_code}：{resp.text[:200]}")
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"LLM 响应格式异常：{exc}") from exc
        return content


def build_provider() -> OpenAiCompatibleProvider | None:
    """根据配置构建 Provider；未配置时返回 None（进入离线模式）。"""
    if not settings.llm_configured:
        return None
    return OpenAiCompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
    )
