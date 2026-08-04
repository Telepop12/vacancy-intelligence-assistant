"""
pytest configuration for Vacancy Intelligence Assistant QA suite.

Run from vacancy_ai_assistant/:
    pytest qa/
    pytest qa/ -v
    pytest qa/ -k "intake or resume"
    pytest qa/ -m "no_llm"   # only tests that don't need an API key
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture(autouse=True)
def _no_llm_key_by_default(request, monkeypatch):
    """
    Force-disable the API key for every test NOT marked `llm`.

    Without this, tests running through the full pipeline silently made live
    Sonnet calls whenever a real key sat in .env: the "offline" suite took
    7 minutes and cost money per run. Tests that genuinely need the LLM must
    carry @pytest.mark.llm.
    """
    if request.node.get_closest_marker("llm"):
        yield
        return
    from core import llm
    monkeypatch.setattr(llm, "get_api_key", lambda: "")
    # Заглушку в окружении наследуют CLI-подпроцессы функциональных тестов.
    # Именно заглушка, НЕ пустая строка: Windows удаляет пустые переменные
    # окружения при передаче в подпроцесс, и тот прочитал бы реальный ключ
    # из .env. Значение с префиксом «sk-ant-ВАШ» get_api_key считает
    # ненастроенным ключом.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-ВАШ-disabled-in-tests")
    yield
