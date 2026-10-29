"""Публичный фасад единого LLM-маршрутизатора.

Импорты оставлены в `core.llm`, чтобы агенты и внешние сценарии сохраняли
прежний путь. Реализация провайдеров находится в `core.llm_router`.
"""
from core.llm_router import (  # noqa: F401
    ResearchResult,
    _DEFAULTS,
    _complete_json,
    _extract_json,
    _ollama_chat,
    _openai_client,
    call_json,
    call_research,
    get_api_key,
    load_llm_config,
    provider_config,
    provider_for,
)
