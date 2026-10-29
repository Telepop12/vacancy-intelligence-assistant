"""Сито отраслевых практик: вакансия + компания + реальный внешний URL."""
import copy

import pytest

from agents import company_research as cr
from agents import practice_research as pr
from core.llm import ResearchResult

pytestmark = pytest.mark.no_llm

VACANCY = "Управление контакт-центром и цифровыми каналами записи пациентов."
COMPANY = "Сеть из 33 клиник в четырёх регионах."
URL = "https://provider.example/cases/clinic?year=2025"


def _practice(**changes):
    return {"title": "Помощник оператора", "process": "Запись пациента оператором",
            "application": "Подсказки при выборе услуги и времени приёма",
            "metric": "Доля обращений, завершившихся записью; время разговора",
            "vacancy_quote": "цифровыми каналами записи пациентов",
            "company_quote": "33 клиник в четырёх регионах",
            "fit": "Единый сценарий записи для распределённой сети",
            "limits": "Проверить интеграцию с расписаниями и исходную конверсию",
            "sources": [URL], **changes}


def _profile():
    return cr.CompanyProfile(company="Тест-Клиника", summary=COMPANY)


def test_accepts_concrete_practice_with_both_anchors_and_real_url():
    brief = pr.filter_practices({"practices": [_practice()]}, [{"url": URL}], VACANCY, COMPANY)
    assert len(brief.practices) == 1
    p = brief.practices[0]
    assert p.id == "P1" and p.sources == [URL]
    assert "Запись пациента" in p.summary and "Доля обращений" in p.summary
    assert "Подсказки" in p.application


@pytest.mark.parametrize("changes", [
    {"vacancy_quote": "Разработка моделей компьютерного зрения"},
    {"company_quote": "Промышленный холдинг из десяти заводов"},
    {"company_quote": "33"},
    {"application": ""},
    {"metric": ""},
    {"sources": ["https://provider.example/cases/invented"]},
    {"sources": ["https://provider.example/cases/clinic?year=2026"]},
])
def test_rejects_missing_context_or_evidence_even_on_same_domain(changes):
    brief = pr.filter_practices({"practices": [_practice(**changes)]}, [{"url": URL}], VACANCY, COMPANY)
    assert brief.practices == [] and brief.rejected


def test_company_context_preserves_full_verified_facts_not_unverified_sections():
    profile = _profile()
    profile.sections = [
        cr.CompanySection(topic="ИТ", text="x" * 4000 + " Общая МИС для клиник.", verified=True),
        cr.CompanySection(topic="Собственники", text="Неподтверждённая информация", verified=False),
    ]
    context = pr.company_context(profile)
    assert "Общая МИС" in context and "Неподтверждённая" not in context


def test_search_receives_both_inputs_and_cache_is_specific_to_context(monkeypatch):
    calls = []

    def fake(key, prompt):
        calls.append(prompt)
        return ResearchResult(data={"practices": [_practice()]}, sources=[{"url": URL}], searches=1)

    monkeypatch.setattr(pr, "_call_research", fake)
    first = pr.get_practices("CIO", "Клиника", VACANCY, _profile(), api_key="test")
    second = pr.get_practices("CIO", "Клиника", VACANCY, _profile(), api_key="test")
    assert first.practices and second.from_cache and len(calls) == 1
    assert VACANCY in calls[0] and COMPANY in calls[0]
    pr.get_practices("CIO", "Клиника", VACANCY + " Бюджетирование.", _profile(), api_key="test")
    changed = _profile()
    changed.summary += " Открытие нового госпиталя."
    pr.get_practices("CIO", "Клиника", VACANCY, changed, api_key="test")
    assert len(calls) == 3


def test_empty_or_fabricated_search_is_not_cached(monkeypatch):
    calls = []

    def fake(*args):
        calls.append(1)
        return ResearchResult(data={"practices": [_practice()]}, sources=[{"url": URL}], searches=0)

    monkeypatch.setattr(pr, "_call_research", fake)
    for _ in range(2):
        result = pr.get_practices("CIO", "Клиника", VACANCY, _profile(), api_key="test")
        assert not result.practices
    assert len(calls) == 2 and not pr.CACHE_DIR.exists()


def test_no_company_context_does_not_start_search(monkeypatch):
    def fail(*args):
        raise AssertionError("Нет оснований для отраслевого поиска")

    monkeypatch.setattr(pr, "_call_research", fail)
    result = pr.get_practices("CIO", "Клиника", VACANCY, cr.CompanyProfile(), api_key="test")
    assert not result.practices and result.note


def test_improve_uses_filtered_practices_not_model_generated_slogans(monkeypatch, tmp_path):
    from agents import interview_prep as ip
    from qa.test_prep import _setup, _mock_llm, _STAGE7

    data = copy.deepcopy(_STAGE7)
    data["trends"] = ["AI с измеримым эффектом и контролем доступа"]
    data["items"].append({"area": "Неприменимая отрасль", "basis": "отрасль",
                          "hypothesis": "Общее обещание", "practice_ids": ["P999"]})
    fake = _mock_llm(override={"improve": data})
    _setup(monkeypatch, tmp_path, fake)
    pkg = ip.PrepPackage(package_id="proof", vacancy_title="CIO")
    ip._stage_improve(pkg, "test", VACANCY, "CIO", "Клиника", "Резюме", "Факты", COMPANY)
    assert all("контролем доступа" not in t for t in pkg.improvements.trends)
    assert "Порожний пробег" in pkg.improvements.trends[0]
    assert "Неприменимая отрасль" not in [i.area for i in pkg.improvements.items]
    assert "practice_brief" not in fake.calls["prompts"]["improve"]
    assert "https://example.org/case" in fake.calls["prompts"]["improve"]
    ip._save(pkg)
    loaded = ip.load_saved_prep("proof")
    assert loaded.improvements.practices[0].id == "P1"
    assert loaded.improvements.items[1].practice_ids == ["P1"]
    text = (tmp_path / "proof.md").read_text(encoding="utf-8")
    assert "Опора в вакансии" in text and "https://example.org/case" in text


def test_search_failure_keeps_vacancy_hypotheses_but_no_invented_trends(monkeypatch, tmp_path):
    from agents import interview_prep as ip
    from qa.test_prep import _setup, _mock_llm

    _setup(monkeypatch, tmp_path, _mock_llm())

    def fail(*args, **kwargs):
        raise RuntimeError("search failed")

    monkeypatch.setattr(pr, "get_practices", fail)
    pkg = ip.PrepPackage()
    ip._stage_improve(pkg, "test", VACANCY, "CIO", "Клиника", "Резюме", "Факты", COMPANY)
    assert not pkg.improvements.trends and pkg.improvements.research_note
    assert [i.basis for i in pkg.improvements.items] == ["вакансия"]


def test_practice_sources_are_clickable_in_page(monkeypatch, tmp_path):
    from qa.test_prep import _client, _setup, _mock_llm
    from agents import interview_prep as ip

    client, _ = _client(monkeypatch, tmp_path)
    _setup(monkeypatch, tmp_path, _mock_llm())
    ip.build_prep(vacancy_text=VACANCY, title="CIO", company="Клиника", package_id="hh_900",
                  resume_text="Резюме", stories_text="")
    page = client.get("/prep/900")
    assert page.status_code == 200
    assert 'href="https://example.org/case"' in page.text
    assert 'href="#practice-P1"' in page.text
    assert "Почему эти практики подходят" in page.text
