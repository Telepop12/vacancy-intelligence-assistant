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
    Force-disable every LLM provider for tests NOT marked `llm`.

    Without this, tests running through the full pipeline silently made live
    Earlier the suite could make paid API calls when a real key sat in .env.
    With Ollama as the default it could also silently call the local model.
    Tests that genuinely need an LLM must carry @pytest.mark.llm.
    """
    if request.node.get_closest_marker("llm"):
        yield
        return
    from core import llm
    monkeypatch.setattr(llm, "get_api_key", lambda purpose=None: "")
    # Флаг наследуют CLI-подпроцессы; он запрещает и OpenAI, и локальный
    # Ollama, поэтому офлайн-suite остаётся детерминированным.
    monkeypatch.setenv("LLM_DISABLED", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-ВАШ-disabled-in-tests")
    yield


@pytest.fixture(autouse=True)
def _company_archive_in_tmp(tmp_path, monkeypatch):
    """
    Архив справок по компаниям (output/companies/) в тестах — во временной
    папке: сборка пакета подготовки пишет туда результат ресёрча, и без
    подмены тесты засоряли бы настоящий архив выдуманными компаниями.
    """
    from agents import company_research as cr
    from agents import practice_research as pr
    monkeypatch.setattr(cr, "ARCHIVE_DIR", tmp_path / "_companies_archive")
    monkeypatch.setattr(pr, "CACHE_DIR", tmp_path / "_practice_research")
    yield
