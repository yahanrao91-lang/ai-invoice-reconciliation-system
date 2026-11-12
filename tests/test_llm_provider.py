"""LLM Provider 审计测试：HTTP 错误、超时、无效 JSON、密钥保护、配置开关。

真实外部模型调用需要用户配置 API Key，本套测试全部使用 mock，不发起真实网络请求。
"""
import requests
import pytest

from invoice_matching.ai.llm_provider import (
    LlmError,
    OpenAiCompatibleProvider,
    build_provider,
)
from invoice_matching.config import settings


class _Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code = status
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


def _provider(key="sk-TEST-KEY"):
    return OpenAiCompatibleProvider("https://example.com/v1", key, "test-model", timeout=5)


def test_provider_chat_ok(monkeypatch):
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: _Resp(200, {"choices": [{"message": {"content": "hi"}}]}),
    )
    assert _provider().chat([]) == "hi"


def test_provider_sends_bearer_auth(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["auth"] = headers["Authorization"]
        captured["model"] = json["model"]
        return _Resp(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    _provider().chat([])
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer sk-TEST-KEY"
    assert captured["model"] == "test-model"


def test_provider_http_error(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(500, text="server down"))
    with pytest.raises(LlmError) as exc:
        _provider().chat([])
    assert "500" in str(exc.value)


def test_provider_timeout(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("connect timeout")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(LlmError) as exc:
        _provider().chat([])
    assert "请求失败" in str(exc.value)


def test_provider_invalid_json_body(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(200, body=None))
    with pytest.raises(LlmError):
        _provider().chat([])


def test_provider_missing_choices(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(200, {"unexpected": 1}))
    with pytest.raises(LlmError):
        _provider().chat([])


def test_provider_does_not_leak_api_key(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(LlmError) as exc:
        _provider(key="sk-SUPER-SECRET").chat([])
    assert "sk-SUPER-SECRET" not in str(exc.value)


def test_provider_http_error_does_not_leak_key(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(401, text="unauthorized"))
    with pytest.raises(LlmError) as exc:
        _provider(key="sk-SUPER-SECRET").chat([])
    assert "sk-SUPER-SECRET" not in str(exc.value)


def test_build_provider_none_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "")
    assert build_provider() is None


def test_build_provider_returns_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_base_url", "https://x/v1")
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_model", "m")
    p = build_provider()
    assert p is not None
    assert p.model == "m"
