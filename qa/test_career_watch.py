"""
pytest: Career Watch — обходчик карьерных страниц. Всё офлайн: сеть замокана.
"""
import json

import pytest

from agents import career_watch as cw
from agents import hh_api, hh_search, vacancy_store
from core.models import CandidateProfile, ScoringGroup


def _profile() -> CandidateProfile:
    return CandidateProfile(
        name="Тест", target_roles=["CIO"],
        scoring_groups={"core": ScoringGroup(weight=100, keywords=["ИТ-стратегия"])},
        red_flags={}, seniority_keywords=[],
    )


_CFG = {
    "title_include": ["директор", r"\bcio\b", r"\bhead\b"],
    "title_include_weak": ["руководител", "начальник"],
    "title_context": [r"\bit\b", r"\bит\b", "цифров", "информац"],
    "title_exclude": ["продаж", "стаж[её]р", r"\bводител"],
    "hh_query_default": "директор OR CIO",
    "max_new_per_company": 10,
    "max_hh_companies_per_run": 8,
    "companies": [],
}

_LIST_HTML = """<html><body>
<a href="/vacancies/direktor-po-it/">Директор по ИТ</a>
<a href="/vacancies/direktor-po-prodazham/">Директор по продажам</a>
<a href="https://career.example.com/vacancies/operator-linii/">Оператор линии</a>
<a href="/vacancies/moscow/">Москва</a>
<a href="/about/">О компании</a>
<a href="/vacancies/rukovoditel-cifrovizacii/?from=list">Руководитель цифровизации</a>
</body></html>"""

_VACANCY_HTML = """<html><body><h1>Директор по ИТ</h1>
<p>Обязанности: разработка ИТ-стратегия компании и цифровизация производства.</p>
<p>Требования: опыт руководства ИТ-функцией от 5 лет.</p><p>Условия: офис, ДМС.</p>
</body></html>"""


@pytest.fixture()
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(cw, "STATE_PATH", tmp_path / "cw_state.json")
    monkeypatch.setattr(cw, "SNAP_DIR", tmp_path / "snaps")
    monkeypatch.setattr(hh_search, "STATE_PATH", tmp_path / "search.json")
    monkeypatch.setattr(vacancy_store, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(hh_api, "_COOLDOWN_PATH", tmp_path / "cooldown.json")
    monkeypatch.setattr(cw, "load_config", lambda: dict(_CFG))
    monkeypatch.setattr(cw, "_site_sleep", lambda: None)
    monkeypatch.setattr(cw.time, "sleep", lambda s: None)


# ---------------------------------------------------------------------------
# Извлечение
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
def test_extract_links_pattern_and_titles():
    links = cw.extract_links(_LIST_HTML, "https://career.example.com/vacancies/", r"/vacancies/[^/?#]+/?$")
    urls = {l.url: l.title for l in links}
    assert urls["https://career.example.com/vacancies/direktor-po-it/"] == "Директор по ИТ"
    assert "https://career.example.com/vacancies/moscow/" in urls        # город — отсеет фильтр названий
    assert "https://career.example.com/about/" not in urls
    # query-параметры не мешают совпадению по пути
    assert any(u.endswith("rukovoditel-cifrovizacii/?from=list") for u in urls)


@pytest.mark.no_llm
def test_title_filter():
    accept = cw.TitleFilter(_CFG)
    assert accept("Директор по ИТ")
    assert accept("Head of IT")
    assert accept("Руководитель цифровизации")               # слабый титул + контекст
    assert accept("Начальник управления информационных технологий")
    assert not accept("Начальник отделения почтовой связи")   # слабый титул без контекста
    assert not accept("Руководитель склада")
    assert accept("Руководитель ИТ-инфраструктуры")     # «водител» не должен ловить «руководитель»
    assert not accept("Водитель категории C")
    assert not accept("Директор по продажам")                 # exclude сильнее
    assert not accept("Москва")
    assert not accept("Аналитик")                             # «ит» только как слово
    assert not accept("Инженер по информационной безопасности")
    assert not accept("ИТ")                                   # слишком коротко


@pytest.mark.no_llm
def test_extract_json_api_and_embedded():
    api = json.dumps({"data": [
        {"id": 1, "title": "Руководитель ИТ-инфраструктуры", "slug": "rukovoditel-it", "isActive": True},
        {"id": 2, "title": "Оператор колл-центра", "slug": "operator"},
    ]})
    links = cw.extract_json_vacancies(api, "https://job.example.ru/", "https://job.example.ru/vacancies/{slug}")
    assert {l.url for l in links} == {"https://job.example.ru/vacancies/rukovoditel-it",
                                      "https://job.example.ru/vacancies/operator"}

    page = ('<html><script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"items":[{"vacancyId":77,"title":"Директор департамента",'
            '"details":"<p>Обязанности: ИТ-стратегия</p>"}]}}}</script></html>')
    links = cw.extract_json_vacancies(page, "https://job.example.ru/vacancies")
    assert len(links) == 1
    assert links[0].title == "Директор департамента"
    assert links[0].url == "https://job.example.ru/vacancies#77"
    assert "ИТ-стратегия" in links[0].description and "<p>" not in links[0].description


# ---------------------------------------------------------------------------
# Прогон: сайт
# ---------------------------------------------------------------------------

def _site_company() -> dict:
    return {"name": "Пример", "group": 1, "channel": "site",
            "urls": ["https://career.example.com/vacancies/"],
            "link_pattern": r"/vacancies/[^/?#]+/?$"}


@pytest.mark.no_llm
def test_watch_site_company_registers_only_new_matches(monkeypatch, _isolated):
    fetched: list[str] = []

    def _fetch(url, timeout=0):
        fetched.append(url)
        return _LIST_HTML if url.endswith("/vacancies/") else _VACANCY_HTML
    monkeypatch.setattr(cw, "fetch", _fetch)
    cfg = dict(_CFG, companies=[_site_company()])
    monkeypatch.setattr(cw, "load_config", lambda: cfg)

    result = cw.run_watch(_profile())
    r = result.companies[0]
    assert (r.found, r.matched, r.new, r.registered) == (5, 2, 2, 2)
    assert r.error == ""
    assert result.new_total == 2
    # Страницы вакансий загружались только для прошедших фильтр
    assert sum(1 for u in fetched if "direktor-po-it" in u) == 1
    assert not any("prodazham" in u for u in fetched)

    vid = cw.career_vid("https://career.example.com/vacancies/direktor-po-it/")
    rec = hh_search.get_state_item(vid)
    assert rec and rec["source"] == "career:Пример" and rec["company"] == "Пример"
    assert rec["score"] > 0
    assert vacancy_store.load_vacancy(vid)["alternate_url"].endswith("/direktor-po-it/")

    # Повторный прогон: ничего нового, страницы вакансий не трогаем
    fetched.clear()
    result2 = cw.run_watch(_profile())
    assert result2.companies[0].new == 0 and result2.new_total == 0
    assert fetched == ["https://career.example.com/vacancies/"]

    rows = cw.career_triage_rows()
    assert {r["company_tag"] for r in rows} == {"Пример"}
    # Сводка по компании отражает ПОСЛЕДНИЙ прогон
    assert cw.company_rows()[0]["registered"] == 0 and cw.company_rows()[0]["last_run"]


@pytest.mark.no_llm
def test_watch_site_error_does_not_break_run(monkeypatch, _isolated):
    def _fetch(url, timeout=0):
        raise cw.CareerFetchError("HTTP 403")
    monkeypatch.setattr(cw, "fetch", _fetch)
    cfg = dict(_CFG, companies=[_site_company(), dict(_site_company(), name="Второй")])
    monkeypatch.setattr(cw, "load_config", lambda: cfg)
    result = cw.run_watch(_profile())
    assert all("HTTP 403" in r.error for r in result.companies) and len(result.companies) == 2
    assert len(result.errors) == 2
    assert "HTTP 403" in cw.load_state()["companies"]["Второй"]["error"]


@pytest.mark.no_llm
def test_watch_site_per_company_cap(monkeypatch, _isolated):
    many = "".join(f'<a href="/vacancies/dir-{i}/">Директор {i}</a>' for i in range(5))
    monkeypatch.setattr(cw, "fetch", lambda url, timeout=0: many if url.endswith("/vacancies/") else _VACANCY_HTML)
    cfg = dict(_CFG, max_new_per_company=2, companies=[_site_company()])
    monkeypatch.setattr(cw, "load_config", lambda: cfg)
    r = cw.run_watch(_profile()).companies[0]
    assert (r.new, r.registered, r.skipped) == (5, 2, 3)
    # Следующий прогон добирает отложенное
    r2 = cw.run_watch(_profile()).companies[0]
    assert (r2.new, r2.registered, r2.skipped) == (3, 2, 1)


# ---------------------------------------------------------------------------
# Прогон: канал hh
# ---------------------------------------------------------------------------

def _hh_intake(vid: str, name: str) -> dict:
    return {"name": name, "employer": "ХХ", "area": "Москва", "salary": None,
            "alternate_url": f"https://hh.ru/vacancy/{vid}", "published_at": "2026-09-02",
            "hh_id": vid, "description": "Обязанности: ИТ-стратегия. Требования: опыт. Условия: офис."}


@pytest.mark.no_llm
def test_watch_hh_company(monkeypatch, _isolated):
    calls = {}

    def _search(text, area=None, max_pages=1, search_field="name", extra_params=None):
        calls["params"] = extra_params
        return ["501", "502"]
    monkeypatch.setattr(hh_api, "search_vacancy_ids", _search)
    monkeypatch.setattr(
        hh_api, "fetch_vacancies_batch",
        lambda ids: ({"501": _hh_intake("501", "Директор по ИТ"), "502": _hh_intake("502", "Кладовщик")}, {}, False),
    )
    cfg = dict(_CFG, companies=[{"name": "ХХ", "group": 2, "channel": "hh", "hh_employer_id": 4649269}])
    monkeypatch.setattr(cw, "load_config", lambda: cfg)

    r = cw.run_watch(_profile()).companies[0]
    assert calls["params"]["employer_id"] == 4649269
    assert (r.found, r.new, r.matched, r.registered) == (2, 2, 1, 1)
    assert hh_search.get_state_item("501")["source"] == "career:ХХ"
    assert hh_search.get_state_item("502") is None   # не по фильтру — в триаж не попал
    assert len(cw.load_snapshot("ХХ")) == 2           # но в снапшоте есть — не перезагружаем


@pytest.mark.no_llm
def test_hh_channel_respects_cooldown_and_budget(monkeypatch, _isolated):
    monkeypatch.setattr(hh_api, "_cooldown_left", lambda: 15)

    def _no_search(*a, **k):
        raise AssertionError("hh не должен вызываться во время кулдауна")
    monkeypatch.setattr(hh_api, "search_vacancy_ids", _no_search)
    cfg = dict(_CFG, companies=[{"name": "ХХ", "channel": "hh", "hh_employer_id": 1}])
    monkeypatch.setattr(cw, "load_config", lambda: cfg)
    r = cw.run_watch(_profile()).companies[0]
    assert "на паузе" in r.error

    # Бюджет hh-компаний за прогон
    monkeypatch.setattr(hh_api, "_cooldown_left", lambda: 0)
    monkeypatch.setattr(hh_api, "search_vacancy_ids", lambda *a, **k: [])
    cfg = dict(_CFG, max_hh_companies_per_run=1,
               companies=[{"name": "A", "channel": "hh", "hh_employer_id": 1},
                          {"name": "B", "channel": "hh", "hh_employer_id": 2}])
    monkeypatch.setattr(cw, "load_config", lambda: cfg)
    res = cw.run_watch(_profile())
    assert res.companies[0].error == "" and "лимит" in res.companies[1].error
    # Ротация: в следующий прогон очередь у той, что не обходилась
    res2 = cw.run_watch(_profile())
    assert "лимит" in res2.companies[0].error and res2.companies[1].error == ""


@pytest.mark.no_llm
def test_watch_site_partial_url_failure(monkeypatch, _isolated):
    def _fetch(url, timeout=0):
        if url.endswith("?direction=it"):
            raise cw.CareerFetchError("HTTP 404")
        return _LIST_HTML if url.endswith("/vacancies/") else _VACANCY_HTML
    monkeypatch.setattr(cw, "fetch", _fetch)
    comp = dict(_site_company(), urls=["https://career.example.com/vacancies/?direction=it",
                                       "https://career.example.com/vacancies/"])
    monkeypatch.setattr(cw, "load_config", lambda: dict(_CFG, companies=[comp]))
    r = cw.run_watch(_profile()).companies[0]
    assert r.registered == 2 and "HTTP 404" in r.error


@pytest.mark.no_llm
def test_link_title_is_first_chunk():
    html = '<a href="/vacancies/it-partner/"><span>ИТ-партнёр</span><span>Москва</span><span>от 300 000</span></a>'
    links = cw.extract_links(html, "https://career.example.com/", r"/vacancies/")
    assert links[0].title == "ИТ-партнёр"
