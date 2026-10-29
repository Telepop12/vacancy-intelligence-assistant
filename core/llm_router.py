"""Маршрутизация LLM между локальным Ollama и OpenAI Responses API."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "llm.yaml"

_DEFAULTS: dict[str, Any] = {
    "provider": "ollama",
    "routes": {"prep": "openai"},
    "providers": {
        "ollama": {
            "model": "qwen3.8:27b",
            "base_url": "http://127.0.0.1:11434",
            "timeout": 300,
            "keep_alive": "15m",
            "think": False,
            "min_max_tokens": 4000,
        },
        "openai": {
            "model": "gpt-6-astra",
            "effort": "medium",
            "timeout": 600,
            "max_retries": 2,
            "min_max_tokens": 6000,
        },
    },
    "max_json_retries": 1,
}


def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_llm_config() -> dict:
    cfg = _merge({}, _DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            user_cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            if isinstance(user_cfg, dict):
                cfg = _merge(cfg, user_cfg)
        except yaml.YAMLError:
            pass
    return cfg


def _load_dotenv() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def provider_for(purpose: str | None = None, cfg: dict | None = None) -> str:
    cfg = cfg or load_llm_config()
    routes = cfg.get("routes") if isinstance(cfg.get("routes"), dict) else {}
    return str(routes.get(purpose or "") or cfg.get("provider") or "ollama").lower()


def provider_config(provider: str, cfg: dict | None = None) -> dict:
    cfg = cfg or load_llm_config()
    providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    value = providers.get(provider)
    return dict(value) if isinstance(value, dict) else {}


def get_api_key(purpose: str | None = None) -> str:
    """Учетные данные выбранного провайдера; Ollama возвращает локальный маркер."""
    _load_dotenv()
    if os.environ.get("LLM_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return ""
    provider = provider_for(purpose)
    if provider == "ollama":
        return "ollama-local"
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        return key if key and not key.startswith(("sk-ВАШ", "sk-proj-ВАШ")) else ""
    return ""


def _provider_error(provider: str) -> RuntimeError:
    if provider == "openai":
        return RuntimeError("OPENAI_API_KEY не настроен")
    if provider == "ollama":
        return RuntimeError("Ollama недоступен")
    return RuntimeError(f"Неизвестный LLM-провайдер: {provider}")


def _system_text(system: str, cached_prefix: str | None) -> str:
    # Большой общий префикс первым: OpenAI автоматически кеширует одинаковые
    # начала промптов, Ollama получает тот же смысловой порядок.
    return f"{cached_prefix}\n\n{system}" if cached_prefix else system


def _extract_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")].rstrip()
    start, end = raw.find("{"), raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("ожидался JSON-объект", raw, 0)
    return data


def _field(obj, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_dict(obj) -> dict:
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except TypeError:
            return dump()
    return {}


def _ollama_chat(
    system: str,
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    cfg: dict,
) -> tuple[str, str]:
    base_url = os.environ.get("OLLAMA_BASE_URL", "").strip() or str(
        cfg.get("base_url") or "http://127.0.0.1:11434"
    )
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "think": bool(cfg.get("think", False)),
        "keep_alive": str(cfg.get("keep_alive") or "15m"),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(cfg.get("timeout", 300))) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ollama недоступен по адресу {base_url}: {exc}") from exc
    message = body.get("message") if isinstance(body, dict) else None
    text = str((message or {}).get("content") or "")
    reason = str(body.get("done_reason") or "") if isinstance(body, dict) else ""
    return text, "max_tokens" if reason in {"length", "max_tokens"} else reason


def _openai_client(key: str, cfg: dict):
    from openai import OpenAI

    return OpenAI(
        api_key=key,
        timeout=float(cfg.get("timeout", 600)),
        max_retries=int(cfg.get("max_retries", 2)),
    )


def _openai_refusal(response) -> str:
    dump = _as_dict(response)
    for item in dump.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "refusal":
                return str(content.get("refusal") or "модель отклонила запрос")
    return ""


def _openai_json(
    system: str,
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    key: str,
    cfg: dict,
) -> tuple[str, str]:
    params: dict[str, Any] = {
        "model": model,
        "instructions": system,
        "input": prompt,
        "max_output_tokens": max_tokens,
        "text": {"format": {"type": "json_object"}},
        "store": False,
    }
    if cfg.get("effort"):
        params["reasoning"] = {"effort": cfg["effort"]}
    response = _openai_client(key, cfg).responses.create(**params)
    refusal = _openai_refusal(response)
    if refusal:
        raise RuntimeError(f"модель отклонила запрос (refusal): {refusal}")
    status = str(_field(response, "status") or "")
    details = _field(response, "incomplete_details")
    reason = str(_field(details, "reason") or "") if details else ""
    stop = "max_tokens" if status == "incomplete" and reason == "max_output_tokens" else status
    return str(_field(response, "output_text") or ""), stop


def _complete_json(
    provider: str,
    system: str,
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    key: str,
    cfg: dict,
) -> tuple[str, str]:
    if provider == "ollama":
        return _ollama_chat(system, prompt, model=model, max_tokens=max_tokens, cfg=cfg)
    if provider == "openai":
        return _openai_json(
            system, prompt, model=model, max_tokens=max_tokens, key=key, cfg=cfg
        )
    raise _provider_error(provider)


def call_json(
    system: str,
    prompt: str,
    *,
    max_tokens: int = 4000,
    api_key: str | None = None,
    model: str | None = None,
    banned_substrings: list[str] | None = None,
    purpose: str | None = None,
    cached_prefix: str | None = None,
) -> dict:
    """Вернуть JSON-объект через провайдера, выбранного по ``purpose``."""
    full_cfg = load_llm_config()
    provider = provider_for(purpose, full_cfg)
    cfg = provider_config(provider, full_cfg)
    key = api_key or get_api_key(purpose)
    if not key:
        raise _provider_error(provider)
    use_model = model or str(cfg.get("model") or "")
    if not use_model:
        raise RuntimeError(f"Для провайдера {provider} не задана модель")
    system_text = _system_text(system, cached_prefix)
    tokens = max(max_tokens, int(cfg.get("min_max_tokens", 0)))
    attempt_prompt = prompt
    last_err: Exception | None = None
    data: dict | None = None

    for _ in range(1 + int(full_cfg.get("max_json_retries", 1))):
        raw, stop = _complete_json(
            provider,
            system_text,
            attempt_prompt,
            model=use_model,
            max_tokens=tokens,
            key=key,
            cfg=cfg,
        )
        try:
            if stop == "max_tokens":
                raise json.JSONDecodeError("ответ оборван по max_tokens", raw, 0)
            data = _extract_json(raw)
            break
        except json.JSONDecodeError as exc:
            last_err = exc
            tokens = min(int(tokens * 1.6), 32000)
            attempt_prompt = prompt + (
                "\n\nВАЖНО: прошлый ответ оборвался или содержал невалидный JSON. "
                "Сократи формулировки и верни СТРОГО валидный JSON целиком."
            )
    if data is None:
        raise last_err or RuntimeError("модель не вернула JSON")

    if banned_substrings:
        blob = json.dumps(data, ensure_ascii=False)
        hits = [value for value in banned_substrings if value in blob]
        if hits:
            listed = "; ".join(f"«{value}»" for value in hits)
            retry = prompt + (
                f"\n\nВАЖНО: в прошлой попытке встретились запрещённые обороты: {listed}. "
                "Перепиши формулировки без них и верни СТРОГО валидный JSON."
            )
            raw, _ = _complete_json(
                provider,
                system_text,
                retry,
                model=use_model,
                max_tokens=tokens,
                key=key,
                cfg=cfg,
            )
            try:
                data = _extract_json(raw)
            except json.JSONDecodeError:
                pass
    return data


@dataclass
class ResearchResult:
    """Итог OpenAI web search: JSON и фактически возвращённые источники."""

    data: dict = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)
    searches: int = 0
    errors: list[str] = field(default_factory=list)


def _walk_research(node, result: ResearchResult, seen: set[str]) -> None:
    if isinstance(node, dict):
        url = node.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            result.sources.append({"url": url, "title": str(node.get("title") or "")})
        code = None
        if node.get("type") == "error":
            code = node.get("error_code") or node.get("code")
        if isinstance(code, str) and code:
            result.errors.append(code)
        for value in node.values():
            if isinstance(value, (dict, list)):
                _walk_research(value, result, seen)
    elif isinstance(node, list):
        for value in node:
            _walk_research(value, result, seen)


def _openai_research(
    system: str,
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    key: str,
    cfg: dict,
) -> tuple[Any, str, str]:
    params: dict[str, Any] = {
        "model": model,
        "instructions": system,
        "input": prompt,
        "max_output_tokens": max_tokens,
        "reasoning": {"effort": cfg.get("effort", "medium")},
        "tools": [{"type": "web_search"}],
        "tool_choice": "auto",
        "include": ["web_search_call.action.sources"],
        # OpenAI: web_search несовместим с JSON mode. JSON запрашивается
        # инструкцией, проверяется ниже; repair выполняется без инструментов.
        "store": False,
    }
    response = _openai_client(key, cfg).responses.create(**params)
    refusal = _openai_refusal(response)
    if refusal:
        raise RuntimeError(f"модель отклонила запрос (refusal): {refusal}")
    status = str(_field(response, "status") or "")
    details = _field(response, "incomplete_details")
    reason = str(_field(details, "reason") or "") if details else ""
    stop = "max_tokens" if status == "incomplete" and reason == "max_output_tokens" else status
    return response, str(_field(response, "output_text") or ""), stop


def call_research(
    system: str,
    prompt: str,
    *,
    max_tokens: int = 16000,
    api_key: str | None = None,
    model: str | None = None,
    purpose: str | None = None,
    max_searches: int = 8,
    max_fetches: int = 4,
    max_continuations: int = 4,
    cached_prefix: str | None = None,
) -> ResearchResult:
    """Выполнить веб-ресёрч через OpenAI Responses API и вернуть JSON."""
    del max_continuations  # Responses API сам ведёт цикл hosted web_search.
    full_cfg = load_llm_config()
    provider = provider_for(purpose, full_cfg)
    if provider != "openai":
        raise RuntimeError("Веб-ресёрч требует маршрут OpenAI")
    cfg = provider_config(provider, full_cfg)
    key = api_key or get_api_key(purpose)
    if not key:
        raise _provider_error(provider)
    use_model = model or str(cfg.get("model") or "")
    system_text = _system_text(system, cached_prefix)
    tokens = max(max_tokens, int(cfg.get("min_max_tokens", 0)))
    budget = (
        f"\n\nЛимит инструментов: не более {max_searches} поисковых запросов и "
        f"не более {max_fetches} углублённых чтений страниц."
    )
    result = ResearchResult()
    seen: set[str] = set()
    response, raw, stop = _openai_research(
        system_text,
        prompt + budget,
        model=use_model,
        max_tokens=tokens,
        key=key,
        cfg=cfg,
    )
    dump = _as_dict(response)
    _walk_research(dump, result, seen)
    result.searches = sum(
        1 for item in dump.get("output") or [] if item.get("type") == "web_search_call"
    )
    try:
        if stop == "max_tokens":
            raise json.JSONDecodeError("ответ оборван по max_output_tokens", raw, 0)
        result.data = _extract_json(raw)
        return result
    except json.JSONDecodeError:
        retry_prompt = (
            "Ниже ответ уже выполненного веб-поиска. Новых поисков не делай. "
            "Восстанови из него СТРОГО валидный JSON по исходной схеме, сократив формулировки.\n\n"
            + raw
        )
        fixed, _ = _openai_json(
            system_text,
            retry_prompt,
            model=use_model,
            max_tokens=min(int(tokens * 1.6), 32000),
            key=key,
            cfg=cfg,
        )
        result.data = _extract_json(fixed)
        return result
