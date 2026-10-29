"""
pytest: ресёрч компании для подготовки к интервью — офлайн (веб-поиск подменён).
Проверяет сверку источников с тем, что реально вернул поиск, порядок тем,
сжатую справку для других этапов и обёртки вызовов.
"""
import pytest

from agents import company_research as cr
from core.llm import ResearchResult

pytestmark = pytest.mark.no_llm

SEEN = [{"url": "https://www.rusprofile.ru/id/1", "title": "Rusprofile"},
        {"url": "https://tadviser.ru/a/1", "title": "TAdviser"}]


def test_verify_urls_keeps_only_what_search_returned():
    urls = ["https://rusprofile.ru/id/1/",            # тот же адрес без www и со слэшем
            "https://www.rusprofile.ru/id/999",       # тот же сайт — модель укоротила путь
            "https://fake.example/x",                 # сайт, где поиска не было
            "rusprofile.ru/id/1",                     # не адрес
            "https://tadviser.ru/a/1", "https://tadviser.ru/a/1"]   # дубль
    assert cr.verify_urls(urls, SEEN) == ["https://rusprofile.ru/id/1/", "https://www.rusprofile.ru/id/999",
                                          "https://tadviser.ru/a/1"]
    assert cr.verify_urls(urls, []) == []
    assert cr.url_domain("https://www.TAdviser.ru/a/1?x=1") == "tadviser.ru"


def test_build_profile_orders_topics_and_marks_unverified():
    data = {
        "legal_name": "  ООО   «Тест» ",
        "summary": "Сеть клиник.",
        "sections": [
            {"key": "it", "text": "МИС внедрена.", "sources": ["https://tadviser.ru/a/1"]},
            {"topic": "Масштаб и география", "text": "40 клиник.", "sources": ["https://fake.example/x"]},
            {"key": "it", "text": "дубль темы игнорируется", "sources": []},
        ],
        "talking_points": ["  пункт  1 ", "", "пункт 2"],
        "gaps": "Нет данных о численности ИТ.",
    }
    p = cr.build_profile("Тест", data, SEEN, searches=5, errors=["url_too_long"])  # при результатах — не шумим
    assert [s.key for s in p.sections] == [k for k, _t, _h in cr.TOPICS]
    by = {s.key: s for s in p.sections}
    assert by["it"].verified and by["it"].text == "МИС внедрена."
    assert by["scale"].found and not by["scale"].verified          # тема по заголовку, источник выдуман
    assert by["finance"].text == cr.NOT_FOUND and not by["finance"].found
    assert p.legal_name == "ООО «Тест»" and p.talking_points == ["пункт 1", "пункт 2"]
    assert [(s.url, s.title) for s in p.sources] == [("https://tadviser.ru/a/1", "TAdviser")]
    assert p.searches == 5 and p.researched_at and p.note == "" and not p.empty


def test_build_profile_without_search_results_warns():
    p = cr.build_profile("Тест", {"summary": "Что-то из памяти модели.",
                                  "sections": [{"key": "scale", "text": "много", "sources": ["https://a.ru"]}]},
                         [], searches=0, errors=["max_uses_exceeded", "max_uses_exceeded"])
    assert all(not s.verified for s in p.sections)
    assert "не вернул результатов" in p.note and "max_uses_exceeded." in p.note


def test_digest_skips_not_found_and_marks_unverified():
    assert "не собрана" in cr.digest(None) and "не собрана" in cr.digest(cr.CompanyProfile())
    p = cr.build_profile("Тест", {"legal_name": "ООО «Тест»", "summary": "Сеть клиник.", "sections": [
        {"key": "scale", "text": "40 клиник.", "sources": ["https://www.rusprofile.ru/id/1"]},
        {"key": "owners", "text": "Основатель.", "sources": []},
    ]}, SEEN)
    text = cr.digest(p)
    assert text.startswith("ООО «Тест» Сеть клиник.")
    assert "- Масштаб и география: 40 клиник." in text
    assert "- Собственники и группа: Основатель. [не подтверждено источником]" in text
    assert "Финансовые показатели" not in text
    long = cr.digest(p, max_chars=40)
    assert long.endswith("…[справка сокращена]") and len(long) < 80


def test_from_dict_roundtrip():
    from dataclasses import asdict
    p = cr.build_profile("Тест", {"summary": "s", "sections": [
        {"key": "it", "text": "МИС.", "sources": ["https://tadviser.ru/a/1"]}]}, SEEN, searches=3)
    back = cr.from_dict(asdict(p))
    assert back == p and back.sections[5].verified
    assert cr.from_dict(None).empty and cr.from_dict({"sections": ["мусор"]}).sections == []


def test_research_company_calls_search_with_topics(monkeypatch):
    seen = {}

    def fake(api_key, system, prompt, **kw):
        seen.update(kw, system=system, prompt=prompt, key=api_key)
        return ResearchResult(data={"summary": "Сеть клиник.", "sections": []}, sources=SEEN, searches=4)
    monkeypatch.setattr(cr, "_call_research", fake)
    p = cr.research_company("СМ-Клиника", "CIO", "Ищем CIO в сеть клиник", api_key="sk-test")
    assert seen["key"] == "sk-test" and seen["purpose"] == "prep"
    assert "procurement — Закупки ИТ-услуг и подрядчики" in seen["prompt"]
    assert "КОМПАНИЯ (как указана в вакансии): СМ-Клиника" in seen["prompt"]
    assert "в открытых источниках не найдено" in seen["system"]
    assert p.company == "СМ-Клиника" and p.summary == "Сеть клиник." and p.searches == 4


def test_ask_with_search_filters_sources(monkeypatch):
    def fake(api_key, system, prompt, **kw):
        assert kw["max_searches"] == 3 and kw["max_fetches"] == 2 and kw["cached_prefix"] == "РЕЗЮМЕ"
        return ResearchResult(data={"answer": "a", "sources": ["https://tadviser.ru/a/1", "https://x.y/z"]},
                              sources=SEEN)
    monkeypatch.setattr(cr, "_call_research", fake)
    data, urls = cr.ask_with_search("sk", "s", "p", materials="РЕЗЮМЕ")
    assert data["answer"] == "a" and urls == ["https://tadviser.ru/a/1"]


def test_call_research_wrapper_passes_through(monkeypatch):
    from core import llm
    seen = {}

    def fake(system, prompt, **kw):
        seen.update(kw)
        return ResearchResult()
    monkeypatch.setattr(llm, "call_research", fake)
    cr._call_research("sk", "s", "p", max_tokens=7, purpose="prep", max_searches=2, max_fetches=1)
    assert seen == {"max_tokens": 7, "api_key": "sk", "purpose": "prep", "max_searches": 2,
                    "max_fetches": 1, "cached_prefix": None}


# ---------------------------------------------------------------------------
# Архив справок (21.10.2026: веб-поиск платный — сначала архив)
# ---------------------------------------------------------------------------

def _profile(legal="ООО «СМ-Клиника»; управляющая — ООО «Группа Компаний СМ-Клиника»"):
    return cr.build_profile("x", {"legal_name": legal, "summary": "Сеть клиник.", "sections": [
        {"key": "scale", "text": "33 клиники.", "sources": ["https://www.rusprofile.ru/id/1"]}]}, SEEN, searches=6)


def test_company_key_normalizes_brand_and_legal_form():
    assert cr.company_key("Сеть медицинских центров и клиник «СМ-Клиника»") == "см клиника"
    assert cr.company_key("ООО «СМ-Клиника»") == "см клиника"
    assert cr.company_key("СМ-Клиника") == "см клиника"
    assert cr.company_key("ПАО «Сбербанк»") == "сбербанк"
    assert cr.company_key("Группа компаний Самолёт") == "самолет"
    assert cr.company_key("") == "" and cr.company_key("—") == ""


def test_archive_roundtrip_and_aliases():
    path = cr.archive_save("Сеть медицинских центров и клиник «СМ-Клиника»", _profile())
    assert path is not None and path.name == "см-клиника.json" and path.parent == cr.ARCHIVE_DIR
    hit = cr.archive_lookup("ООО «СМ-Клиника»")                 # другое написание — та же компания
    assert hit is not None and hit.from_archive and hit.summary == "Сеть клиник."
    assert hit.sections[0].verified and hit.searches == 6
    assert cr.archive_lookup("Рога и копыта") is None and cr.archive_lookup("") is None


def test_archive_expires_after_half_a_year():
    from datetime import datetime, timedelta
    cr.archive_save("СМ-Клиника", _profile())
    assert cr.archive_lookup("СМ-Клиника", now=datetime.now() + timedelta(days=180)) is not None
    assert cr.archive_lookup("СМ-Клиника", now=datetime.now() + timedelta(days=cr.ARCHIVE_MAX_AGE_DAYS + 1)) is None


def test_archive_skips_empty_and_unverified():
    assert cr.archive_save("Тест", cr.CompanyProfile()) is None
    unverified = cr.build_profile("Тест", {"summary": "из памяти модели"}, [], searches=0)
    assert cr.archive_save("Тест", unverified) is None
    assert cr.archive_save("—", _profile(legal="")) is None       # нет ключа — некуда класть
    assert not cr.ARCHIVE_DIR.exists() or not list(cr.ARCHIVE_DIR.glob("*.json"))


def test_get_company_profile_uses_archive_before_search(monkeypatch):
    calls = {"n": 0}

    def fake(api_key, system, prompt, **kw):
        calls["n"] += 1
        return ResearchResult(data={"legal_name": "ООО «СМ-Клиника»", "summary": f"Поиск №{calls['n']}.",
                                    "sections": [{"key": "it", "text": "МИС.", "sources": ["https://tadviser.ru/a/1"]}]},
                              sources=SEEN, searches=5)
    monkeypatch.setattr(cr, "_call_research", fake)
    first = cr.get_company_profile("«СМ-Клиника»", "CIO", "v", api_key="sk")
    assert calls["n"] == 1 and not first.from_archive and first.summary == "Поиск №1."
    second = cr.get_company_profile("ООО «СМ-Клиника»", "CTO", "v", api_key="sk")
    assert calls["n"] == 1 and second.from_archive and second.summary == "Поиск №1."   # без поиска
    fresh = cr.get_company_profile("СМ-Клиника", "CIO", "v", api_key="sk", force=True)
    assert calls["n"] == 2 and not fresh.from_archive
    assert cr.archive_lookup("СМ-Клиника").summary == "Поиск №2."                     # архив обновлён
    assert len(list(cr.ARCHIVE_DIR.glob("*.json"))) == 1
