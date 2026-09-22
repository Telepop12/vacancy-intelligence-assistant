"""
pytest: единый LLM-шлюз core/llm.py — офлайн, клиент SDK подменён.
Проверяет стриминг, stop_reason (max_tokens, refusal), повтор по JSON и по
запрещённому обороту.
"""
import json

import anthropic
import pytest

from core import llm

pytestmark = pytest.mark.no_llm


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, text, stop="end_turn", thinking_first=True):
        blocks = [_Block(text)]
        if thinking_first:
            th = type("Th", (), {"type": "thinking", "thinking": "…"})()
            blocks.insert(0, th)
        self.content = blocks
        self.stop_reason = stop
        self.stop_details = None


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.msg


class _Messages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream(self, **params):
        self.calls.append(params)
        return _Stream(self.responses.pop(0))

    def create(self, **params):  # непотоковый путь больше не используется
        raise AssertionError("шлюз должен ходить через messages.stream")


def _fake(monkeypatch, responses):
    msgs = _Messages(responses)
    client = type("C", (), {"messages": msgs})()
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: client)
    monkeypatch.setattr(anthropic, "DefaultHttpxClient", lambda **kw: None)
    return msgs


def test_streaming_happy_path(monkeypatch):
    msgs = _fake(monkeypatch, [_Msg('Вот ответ:\n```json\n{"a": 1}\n```')])
    data = llm.call_json("sys", "prompt", max_tokens=100, api_key="sk-test")
    assert data == {"a": 1}
    call = msgs.calls[0]
    cfg = llm.load_llm_config()
    assert call["model"] == cfg["model"] and call["system"] == "sys"
    assert call["max_tokens"] >= cfg["min_max_tokens"]          # нижний порог из конфига
    assert call["output_config"] == {"effort": cfg["effort"]}


def test_max_tokens_stop_triggers_retry_with_bigger_limit(monkeypatch):
    msgs = _fake(monkeypatch, [_Msg('{"a": 1', stop="max_tokens"), _Msg('{"a": 2}')])
    data = llm.call_json("sys", "prompt", api_key="sk-test")
    assert data == {"a": 2} and len(msgs.calls) == 2
    assert msgs.calls[1]["max_tokens"] > msgs.calls[0]["max_tokens"]
    assert "оборвался" in msgs.calls[1]["messages"][0]["content"]


def test_refusal_is_a_clear_error(monkeypatch):
    _fake(monkeypatch, [_Msg("", stop="refusal")])
    with pytest.raises(RuntimeError, match="refusal"):
        llm.call_json("sys", "prompt", api_key="sk-test")


def test_banned_substring_retry(monkeypatch):
    msgs = _fake(monkeypatch, [_Msg('{"t": "результат, а не декларация"}'), _Msg('{"t": "результат"}')])
    data = llm.call_json("sys", "prompt", api_key="sk-test", banned_substrings=[", а не "])
    assert data == {"t": "результат"} and len(msgs.calls) == 2
    assert "запрещённые" in msgs.calls[1]["messages"][0]["content"]


def test_invalid_json_twice_raises(monkeypatch):
    _fake(monkeypatch, [_Msg("не json"), _Msg("опять не json")])
    with pytest.raises(json.JSONDecodeError):
        llm.call_json("sys", "prompt", api_key="sk-test")


def test_purpose_picks_model_from_config(monkeypatch):
    base = dict(llm._DEFAULTS, models={"prep": "claude-opus-5"})
    monkeypatch.setattr(llm, "load_llm_config", lambda: dict(base))
    msgs = _fake(monkeypatch, [_Msg('{"a": 1}'), _Msg('{"a": 1}'), _Msg('{"a": 1}')])
    llm.call_json("s", "p", api_key="sk-test", purpose="prep")
    llm.call_json("s", "p", api_key="sk-test", purpose="package")   # назначения нет в карте — общая модель
    llm.call_json("s", "p", api_key="sk-test", purpose="prep", model="claude-haiku-4-5")  # явная модель сильнее
    assert [c["model"] for c in msgs.calls] == ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]


def test_real_config_maps_prep_to_opus():
    cfg = llm.load_llm_config()
    assert cfg["models"].get("prep") == "claude-opus-5" and cfg["model"] == "claude-sonnet-5"


def test_no_key_is_error(monkeypatch):
    monkeypatch.setattr(llm, "get_api_key", lambda: "")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.call_json("sys", "prompt")
