"""
pytest: hh.ru integration tests — all offline (network calls are monkeypatched).
"""
import pytest

from agents import hh_api, hh_search
from agents.intake import IntakeConfidence, SourceType, from_json, from_url


# ---------------------------------------------------------------------------
# URL detection
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
@pytest.mark.parametrize("url,expected", [
    ("https://hh.ru/vacancy/133742638", "133742638"),
    ("https://spb.hh.ru/vacancy/12345678?from=search", "12345678"),
    ("http://hh.kz/vacancy/999999", "999999"),
    ("https://rabota.by/vacancy/555555", "555555"),
    ("https://hh.ru/employer/12345", None),
    ("https://linkedin.com/jobs/view/42", None),
])
def test_extract_vacancy_id(url, expected):
    assert hh_api.extract_vacancy_id(url) == expected


# ---------------------------------------------------------------------------
# Record flattening
# ---------------------------------------------------------------------------

_API_RECORD = {
    "id": 133742638,
    "name": "Директор по информационным технологиям (CIO)",
    "employer": {"name": "СГМК"},
    "area": {"name": "Кемерово"},
    "salary": {"from": 300000, "to": 400000, "currency": "RUR"},
    "experience": {"name": "Более 6 лет"},
    "employment": {"name": "Полная занятость"},
    "schedule": {"name": "Полный день"},
    "description": (
        "<p>Обязанности: разработка и реализация ИТ-стратегии компании, управление "
        "ИТ-командой из 40 человек, цифровая трансформация производственных процессов, "
        "внедрение ERP и BI-систем, управление ИТ-бюджетом.</p>"
        "<p>Требования: опыт работы CIO или директором по ИТ от 5 лет в производственных "
        "компаниях, опыт защиты ИТ-стратегии перед советом директоров.</p>"
        "<p>Условия: офис, ДМС, конкурентная заработная плата.</p>"
    ),
    "key_skills": [{"name": "ITIL"}, {"name": "ERP"}],
    "alternate_url": "https://hh.ru/vacancy/133742638",
    "published_at": "2026-06-20T10:00:00+0300",
    "archived": False,
}

_JSONLD_RECORD = {
    "@type": "JobPosting",
    "title": "Директор по ИТ",
    "hiringOrganization": {"name": "Тест-Компания"},
    "jobLocation": {"address": {"addressLocality": "Москва"}},
    "baseSalary": {"currency": "RUR", "value": {"minValue": 350000, "maxValue": 500000}},
    "description": "<p>Обязанности: ИТ-стратегия и цифровая трансформация. Требования: опыт управления.</p>",
    "datePosted": "2026-06-25",
}


@pytest.mark.no_llm
def test_api_record_flattening():
    flat = hh_api._api_record_to_intake(_API_RECORD)
    assert flat["name"] == "Директор по информационным технологиям (CIO)"
    assert flat["employer"] == "СГМК"
    assert flat["area"] == "Кемерово"
    assert flat["hh_id"] == "133742638"
    assert "ITIL" in flat["description"]
    assert "Более 6 лет" in flat["description"]


@pytest.mark.no_llm
def test_jsonld_record_flattening():
    flat = hh_api._jsonld_to_intake(_JSONLD_RECORD, "42")
    assert flat["name"] == "Директор по ИТ"
    assert flat["employer"] == "Тест-Компания"
    assert flat["area"] == "Москва"
    assert flat["salary"] == {"from": 350000, "to": 500000, "currency": "RUR"}
    assert flat["alternate_url"].endswith("/vacancy/42")


@pytest.mark.no_llm
def test_flat_record_through_intake():
    flat = hh_api._api_record_to_intake(_API_RECORD)
    vi = from_json(flat, source_name="hh.ru:133742638")
    assert vi.title == "Директор по информационным технологиям (CIO)"
    assert vi.company == "СГМК"
    assert "от 300000" in vi.salary
    assert vi.intake_confidence == IntakeConfidence.HIGH
    assert "<p>" not in vi.normalized_text


# ---------------------------------------------------------------------------
# from_url with mocked fetch
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
def test_from_url_hh_success(monkeypatch):
    monkeypatch.setattr(
        hh_api, "fetch_vacancy_data",
        lambda vid: hh_api._api_record_to_intake(_API_RECORD),
    )
    vi = from_url("https://hh.ru/vacancy/133742638")
    assert vi.source_type == SourceType.URL
    assert vi.source_name == "hh.ru:133742638"
    assert vi.company == "СГМК"
    assert vi.url == "https://hh.ru/vacancy/133742638"


@pytest.mark.no_llm
def test_from_url_hh_error(monkeypatch):
    def _boom(vid):
        raise hh_api.HHApiError("hh.ru вернул HTTP 404")
    monkeypatch.setattr(hh_api, "fetch_vacancy_data", _boom)
    vi = from_url("https://hh.ru/vacancy/1")
    assert vi.intake_confidence == IntakeConfidence.LOW
    assert vi.normalized_text == ""
    assert "404" in vi.confidence_notes[0]


# ---------------------------------------------------------------------------
# Search pipeline with mocked network
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
def test_run_search_triage(monkeypatch, tmp_path):
    monkeypatch.setattr(hh_search, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(
        hh_api, "search_vacancy_ids",
        lambda text, area=None, max_pages=1, search_field="name", extra_params=None: ["101", "102"],
    )
    monkeypatch.setattr(
        hh_api, "fetch_vacancies_batch",
        lambda ids: (
            {vid: dict(hh_api._api_record_to_intake(_API_RECORD), hh_id=vid) for vid in ids},
            {},
        ),
    )

    from web.app import _profile
    result = hh_search.run_search(_profile, queries=["CIO"])

    assert result.found_total == 2
    assert result.new_count == 2
    assert not result.errors
    assert all(item.score > 0 for item in result.items)
    assert result.items[0].recommendation in {"ОТКЛИКАТЬСЯ", "УТОЧНИТЬ", "ПРОПУСТИТЬ"}

    # Second run: everything cached, nothing re-fetched
    result2 = hh_search.run_search(_profile, queries=["CIO"])
    assert result2.new_count == 0
    assert len(result2.items) == 2


@pytest.mark.no_llm
def test_search_config_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(hh_search, "CONFIG_PATH", tmp_path / "absent.yaml")
    cfg = hh_search.load_search_config()
    assert cfg["queries"]
    assert cfg["search_field"] == "name"
