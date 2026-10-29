"""Офлайн-тесты маршрутизатора Ollama/OpenAI."""
import json

import pytest

from core import llm_router as router

pytestmark = pytest.mark.no_llm


def _config():
    return {
        "provider": "ollama",
        "routes": {"prep": "openai"},
        "providers": {
            "ollama": {
                "model": "qwen-test",
                "min_max_tokens": 100,
                "base_url": "http://ollama.test",
            },
            "openai": {
                "model": "gpt-test",
                "effort": "medium",
                "min_max_tokens": 200,
            },
        },
        "max_json_retries": 1,
    }


def test_real_config_routes_local_and_prep():
    cfg = router.load_llm_config()
    assert router.provider_for(None, cfg) == "ollama"
    assert router.provider_for("prep", cfg) == "openai"
    assert cfg["providers"]["ollama"]["model"]
    assert cfg["providers"]["openai"]["model"] == "gpt-6-astra"


def test_get_api_key_is_local_marker_or_openai_key(monkeypatch):
    monkeypatch.delenv("LLM_DISABLED", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-test")
    monkeypatch.setattr(router, "load_llm_config", _config)
    assert router.get_api_key() == "ollama-local"
    assert router.get_api_key("prep") == "sk-proj-test"


def test_default_call_uses_ollama(monkeypatch):
    calls = []

    def fake(system, prompt, **kwargs):
        calls.append((system, prompt, kwargs))
        return '{"ok": true}', "stop"

    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(router, "_ollama_chat", fake)
    data = router.call_json("Система", "Запрос", api_key="local")
    assert data == {"ok": True}
    assert calls[0][2]["model"] == "qwen-test"
    assert calls[0][2]["max_tokens"] == 4000


def test_prep_call_uses_openai(monkeypatch):
    calls = []

    def fake(system, prompt, **kwargs):
        calls.append((system, prompt, kwargs))
        return '{"route": "openai"}', "completed"

    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(router, "_openai_json", fake)
    data = router.call_json("Система", "Запрос", api_key="sk-test", purpose="prep")
    assert data == {"route": "openai"}
    assert calls[0][2]["model"] == "gpt-test"


def test_explicit_model_overrides_route_model(monkeypatch):
    seen = {}

    def fake(system, prompt, **kwargs):
        seen.update(kwargs)
        return "{}", "completed"

    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(router, "_openai_json", fake)
    router.call_json("s", "p", api_key="sk", purpose="prep", model="gpt-custom")
    assert seen["model"] == "gpt-custom"


def test_invalid_json_retries_with_bigger_limit(monkeypatch):
    calls = []
    responses = iter([('{"a": 1', "max_tokens"), ('{"a": 2}', "stop")])

    def fake(provider, system, prompt, **kwargs):
        calls.append((prompt, kwargs["max_tokens"]))
        return next(responses)

    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(router, "_complete_json", fake)
    assert router.call_json("s", "p", api_key="local") == {"a": 2}
    assert len(calls) == 2
    assert calls[1][1] > calls[0][1]
    assert "оборвался" in calls[1][0]


def test_banned_substring_gets_style_retry(monkeypatch):
    calls = []
    responses = iter([
        ('{"t": "результат, а не декларация"}', "stop"),
        ('{"t": "результат"}', "stop"),
    ])

    def fake(provider, system, prompt, **kwargs):
        calls.append(prompt)
        return next(responses)

    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(router, "_complete_json", fake)
    result = router.call_json("s", "p", api_key="local", banned_substrings=[", а не "])
    assert result == {"t": "результат"}
    assert "запрещённые" in calls[1]


def test_invalid_json_twice_raises(monkeypatch):
    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(router, "_complete_json", lambda *a, **kw: ("не json", "stop"))
    with pytest.raises(json.JSONDecodeError):
        router.call_json("s", "p", api_key="local")


def test_cached_prefix_is_first_for_every_provider(monkeypatch):
    seen = {}

    def fake(provider, system, prompt, **kwargs):
        seen["provider"] = provider
        seen["system"] = system
        return "{}", "stop"

    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(router, "_complete_json", fake)
    router.call_json("Этап", "p", api_key="sk", purpose="prep", cached_prefix="РЕЗЮМЕ")
    assert seen == {"provider": "openai", "system": "РЕЗЮМЕ\n\nЭтап"}


def test_openai_request_uses_responses_json_mode(monkeypatch):
    calls = []

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return {
                "status": "completed",
                "output_text": '{"ok": true}',
                "output": [],
            }

    monkeypatch.setattr(
        router,
        "_openai_client",
        lambda key, cfg: type("Client", (), {"responses": Responses()})(),
    )
    raw, stop = router._openai_json(
        "sys", "prompt", model="gpt-test", max_tokens=321, key="sk", cfg={"effort": "high"}
    )
    assert json.loads(raw) == {"ok": True} and stop == "completed"
    assert calls[0]["text"] == {"format": {"type": "json_object"}}
    assert calls[0]["reasoning"] == {"effort": "high"}
    assert calls[0]["store"] is False


def test_research_collects_sources_and_search_count(monkeypatch):
    response = {
        "status": "completed",
        "output_text": '{"summary": "ok"}',
        "output": [
            {
                "type": "web_search_call",
                "action": {
                    "sources": [
                        {"url": "https://a.example/1", "title": "A"},
                        {"url": "https://a.example/1", "title": "duplicate"},
                    ]
                },
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [
                            {"type": "url_citation", "url": "https://b.example/2", "title": "B"}
                        ],
                    }
                ],
            },
        ],
    }
    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(
        router,
        "_openai_research",
        lambda *a, **kw: (response, response["output_text"], "completed"),
    )
    result = router.call_research("s", "p", api_key="sk", purpose="prep")
    assert result.data == {"summary": "ok"}
    assert result.searches == 1
    assert [source["url"] for source in result.sources] == [
        "https://a.example/1",
        "https://b.example/2",
    ]


def test_research_bad_json_repairs_without_another_search(monkeypatch):
    response = {
        "status": "completed",
        "output_text": "не json",
        "output": [{"type": "web_search_call", "action": {"sources": []}}],
    }
    repairs = []
    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(router, "_openai_research", lambda *a, **kw: (response, "не json", "completed"))

    def repair(system, prompt, **kwargs):
        repairs.append(prompt)
        return '{"ok": true}', "completed"

    monkeypatch.setattr(router, "_openai_json", repair)
    result = router.call_research("s", "p", api_key="sk", purpose="prep")
    assert result.data == {"ok": True}
    assert "Новых поисков не делай" in repairs[0]


def test_research_requires_openai_route(monkeypatch):
    monkeypatch.setattr(router, "load_llm_config", _config)
    with pytest.raises(RuntimeError, match="OpenAI"):
        router.call_research("s", "p", api_key="local")


def test_openai_route_without_key_is_clear_error(monkeypatch):
    monkeypatch.setattr(router, "load_llm_config", _config)
    monkeypatch.setattr(router, "get_api_key", lambda purpose=None: "")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        router.call_json("s", "p", purpose="prep")


def test_web_search_does_not_enable_incompatible_json_mode(monkeypatch):
    calls = []

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            assert "text" not in kwargs, "OpenAI rejects web search with JSON mode"
            return {"status": "completed", "output_text": '{"ok": true}', "output": []}

    monkeypatch.setattr(router, "_openai_client",
                        lambda key, cfg: type("Client", (), {"responses": Responses()})())
    response, raw, stop = router._openai_research(
        "Return JSON", "Search and return JSON", model="gpt-test", max_tokens=100,
        key="test", cfg={"effort": "medium"})
    assert json.loads(raw) == {"ok": True} and stop == "completed"
    assert calls[0]["include"] == ["web_search_call.action.sources"]
