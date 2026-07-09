"""
pytest: Application Package layer — offline (LLM mocked).
"""
import pytest

from agents import application_package as ap
from agents.application_package import ApplicationPackage


_LLM_RESPONSE = {
    "letter": (
        "Добрый день!\n\n"
        "Вы ищете CIO для цифровой трансформации производственной компании — "
        "это ровно профиль моих последних восьми лет.\n\n"
        "- В МВПС-Сервис построил ИТ-функцию с нуля: 4 конфигурации 1С, BI, SLA 99,9%.\n"
        "- В УРАЛХИМе цифровые двойники дали прирост производства на 1,5–3%.\n\n"
        "Готов рассказать детали на коротком звонке.\n"
        "Вячеслав Гришкин, +7 (929) 999-66-19, vyacheslav.grishkin@gmail.com"
    ),
    "recommended_variant": "cdto",
    "variant_reasoning": "Вакансия делает упор на трансформацию и данные.",
    "hooks": ["трансформация → УРАЛХИМ", "1С → МВПС-Сервис"],
}


@pytest.mark.no_llm
def test_build_package_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ap, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(ap, "_call_llm", lambda api_key, prompt: _LLM_RESPONSE)

    pkg = ap.build_package(
        vacancy_text="Ищем CIO для трансформации",
        title="CIO",
        company="Тест",
        package_id="hh_123",
        resume_text="резюме",
    )
    assert not pkg.error
    assert pkg.recommended_variant == "cdto"
    assert "CDTO" in pkg.variant_name
    assert (tmp_path / "hh_123.json").exists()
    assert (tmp_path / "hh_123.md").exists()

    loaded = ap.load_saved_package("hh_123")
    assert loaded is not None
    assert loaded.letter == pkg.letter


@pytest.mark.no_llm
def test_build_package_facts_in_prompt(monkeypatch, tmp_path):
    """The facts base must reach the LLM prompt."""
    monkeypatch.setattr(ap, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ap, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(ap, "load_facts", lambda: "ФАКТ-МАРКЕР-42")
    captured = {}

    def fake_llm(api_key, prompt):
        captured["prompt"] = prompt
        return _LLM_RESPONSE

    monkeypatch.setattr(ap, "_call_llm", fake_llm)
    ap.build_package(vacancy_text="v", package_id="hh_1", resume_text="r")
    assert "ФАКТ-МАРКЕР-42" in captured["prompt"]


@pytest.mark.no_llm
def test_build_package_no_key(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ap, "_get_api_key", lambda: "")
    pkg = ap.build_package(vacancy_text="v", package_id="hh_2", resume_text="r")
    assert pkg.error
    assert not (tmp_path / "hh_2.json").exists()


@pytest.mark.no_llm
def test_empty_letter_is_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ap, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(ap, "_call_llm", lambda a, p: {"letter": "", "recommended_variant": "cio"})
    pkg = ap.build_package(vacancy_text="v", package_id="hh_3", resume_text="r")
    assert pkg.error
    assert not (tmp_path / "hh_3.json").exists()


@pytest.mark.no_llm
def test_word_count():
    assert ap.letter_word_count("Добрый день! Готов к звонку.") == 5
    assert ap.letter_word_count("") == 0


@pytest.mark.no_llm
def test_load_missing_package(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "OUTPUT_DIR", tmp_path)
    assert ap.load_saved_package("hh_none") is None


@pytest.mark.no_llm
def test_package_route_cold_path(monkeypatch, tmp_path):
    """Regression: /package/hh/{id} cold path must resolve all names in web.app
    (a missing import surfaced as NameError only when the cache was empty)."""
    from fastapi.testclient import TestClient
    import web.app as webapp

    from agents import vacancy_store as vs
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(ap, "OUTPUT_DIR", tmp_path)  # empty cache → cold path
    monkeypatch.setattr(
        webapp.hh_api, "fetch_vacancy_data",
        lambda vid: {"name": "CIO", "employer": "Тест", "description": "текст",
                     "alternate_url": "https://hh.ru/vacancy/1"},
    )
    monkeypatch.setattr(
        webapp, "build_package",
        lambda **kw: ApplicationPackage(package_id="hh_1", vacancy_title="CIO",
                                        letter="Добрый день!", variant_name="CIO",
                                        recommended_variant="cio"),
    )
    client = TestClient(webapp.app)
    resp = client.get("/package/hh/1")
    assert resp.status_code == 200
    assert "Добрый день!" in resp.text
