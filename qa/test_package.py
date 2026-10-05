"""
pytest: Application Package layer — offline (LLM mocked).
Письмо — рамка «3+3» (единственный русскоязычный формат с 05.10.2026).
"""
import json

import pytest

from agents import application_package as ap
from agents.application_package import ApplicationPackage

_REFERENCE = (
    "Добрый день!\n\nПрошу рассмотреть моё резюме на позицию руководителя дирекции AI.\n\n"
    "Мой профиль — 20+ лет …\n\nКлючевые компетенции и достижения, релевантные позиции:\n\n1. …\n\n"
    "Чем конкретно могу усилить компанию на этой позиции:\n\n— …\n\n"
    "Более подробно опыт и реализованные проекты представлены в резюме.\n\n"
    "С уважением,\nВячеслав Гришкин\n+7 (929) 999-66-19 | vyacheslav.grishkin@gmail.com\n"
    "Telegram: @V_Grishkin | Портфель решений: grishkin.org"
)

_LLM_RESPONSE = {
    "competencies": [
        {"title": "Управление ИТ-функцией и ИТ-стратегия",
         "points": ["В МВПС-Сервис актуализировал ИТ-стратегию, команда 30+, бюджет 200+ млн ₽."]},
        {"title": "Операции и эксплуатация", "points": ["Внедрил 4 конфигурации 1С, доступность сервисов 99,9%."]},
        {"title": "Партнёрство с бизнесом", "points": ["Модель бизнес-кураторов (УРАЛХИМ, МВПС-Сервис)."]},
        "мусор",
    ],
    "offers": [
        {"task": "разработать ИТ-стратегию", "offer": "выстроить ИТ-стратегию и портфель проектов: аудит, приоритизация",
         "result": "ИТ-стратегия"},
        {"task": "стабильность инфраструктуры", "offer": "обеспечить стабильность инфраструктуры: регламенты, контроль инцидентов",
         "result": "Операции и эксплуатация"},
        {"task": "взаимодействие с бизнесом", "offer": "выстроить партнёрство ИТ с бизнесом: кураторы, BI-отчётность",
         "effect": "Партнёрство с бизнесом"},
        "мусор",
    ],
    "letter": (
        "Добрый день!\n\nПрошу рассмотреть моё резюме на позицию директора по информационным технологиям.\n\n"
        "Мой профиль — 29 лет в управлении технологическим развитием.\n\n"
        "Ключевые компетенции и достижения, релевантные позиции:\n\n"
        "1. Управление ИТ-функцией и ИТ-стратегия. — В МВПС-Сервис актуализировал ИТ-стратегию.\n\n"
        "Чем конкретно могу усилить компанию на этой позиции:\n\n"
        "— Выстроить ИТ-стратегию и портфель проектов: аудит, приоритизация.\n\n"
        "Более подробно опыт и реализованные проекты представлены в резюме.\n\n"
        "С уважением,\nВячеслав Гришкин\n+7 (929) 999-66-19"
    ),
    "recommended_variant": "cdto",
    "variant_reasoning": "Вакансия делает упор на трансформацию и данные.",
    "hooks": ["трансформация → УРАЛХИМ", "1С → МВПС-Сервис"],
}

_SCREENER_RESPONSE = {
    "screener_qa": [
        {"question": "Расскажите про опыт управления ИТ-бюджетом.",
         "answer": "Владел бюджетом 200+ млн ₽: CAPEX на инфраструктуру, OPEX на команду и лицензии.",
         "value_added": "структура CAPEX/OPEX — из факт-базы"},
    ],
}


@pytest.fixture
def ready(monkeypatch, tmp_path):
    """Ключ, подменённые вызовы модели, эталон во временном файле, каталог вывода."""
    ref = tmp_path / "reference.md"
    ref.write_text("> комментарий, в промпт не идёт\n\n" + _REFERENCE, encoding="utf-8")
    monkeypatch.setattr(ap, "REFERENCE_PATH", ref)
    monkeypatch.setattr(ap, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ap, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(ap, "_call_llm", lambda api_key, prompt: _LLM_RESPONSE)
    monkeypatch.setattr(ap, "_call_screener", lambda prompt: _SCREENER_RESPONSE)
    return tmp_path


@pytest.mark.no_llm
def test_build_package_happy_path(ready):
    tmp_path = ready
    pkg = ap.build_package(vacancy_text="Ищем CIO для трансформации", title="CIO", company="Тест",
                           package_id="hh_123", resume_text="резюме")
    assert not pkg.error
    assert pkg.recommended_variant == "cdto" and "CDTO" in pkg.variant_name
    assert pkg.hooks == ["трансформация → УРАЛХИМ", "1С → МВПС-Сервис"]

    # рамка «3+3»: три требования, три дела; мусор отброшен; ось — в effect
    assert [c.title for c in pkg.competencies][:1] == ["Управление ИТ-функцией и ИТ-стратегия"] and len(pkg.competencies) == 3
    assert [o.effect for o in pkg.offers] == ["ИТ-стратегия", "Операции и эксплуатация", "Партнёрство с бизнесом"]
    # стаж «20+ лет» и подпись из эталона — детерминированно
    assert "20+ лет" in pkg.letter and "29 лет" not in pkg.letter
    assert pkg.letter.endswith("Telegram: @V_Grishkin | Портфель решений: grishkin.org")

    assert pkg.screener_qa[0].question.startswith("Расскажите")
    md = (tmp_path / "hh_123.md").read_text(encoding="utf-8")
    for fragment in ["## Сопроводительное письмо (рамка «3+3»)", "## Три требования → три доказательства",
                     "## Три дела после выхода", "Партнёрство с бизнесом", "ИИ-скринером"]:
        assert fragment in md, fragment

    loaded = ap.load_saved_package("hh_123")
    assert loaded is not None and loaded.letter == pkg.letter
    assert loaded.competencies[2].title == "Партнёрство с бизнесом" and loaded.offers[0].effect == "ИТ-стратегия"
    assert loaded.screener_qa[0].value_added.startswith("структура")


@pytest.mark.no_llm
def test_letter_prompt_is_three_plus_three():
    sp = ap._SYSTEM_PROMPT
    assert "РАМКА «3+3»" in sp and "единственный русскоязычный формат" in sp
    assert "Ключевые компетенции и достижения, релевантные" in sp and "РОВНО ТРИ нумерованных пункта" in sp
    assert "CIO, директор по ИТ — ИТ-стратегия" in sp and "CAIO, директор по AI" in sp
    assert "СТАЖ в письме — «20+ лет»" in sp and "ЖЕЛЕЗНОЕ ПРАВИЛО" in sp and "СТРОГО не больше 300" in sp
    assert "Прошу рассмотреть моё" in sp
    assert not hasattr(ap, "_SYSTEM_PROMPT_V2") and not hasattr(ap, "_USER_TEMPLATE_V2")
    ut = ap._USER_TEMPLATE
    assert "{reference}" in ut and "{variants_list}" in ut
    assert ut.index('"competencies"') < ut.index('"offers"') < ut.index('"letter"') < ut.index('"recommended_variant"')


@pytest.mark.no_llm
def test_reference_letter_loaded_into_prompt(ready, monkeypatch):
    tmp_path = ready
    assert ap.load_reference_letter().startswith("Добрый день!")
    seen = {}

    def fake(api_key, prompt):
        seen["prompt"] = prompt
        return _LLM_RESPONSE
    monkeypatch.setattr(ap, "_call_llm", fake)
    ap.build_package(vacancy_text="v", title="CIO", package_id="hh_ref", resume_text="r")
    assert "ЭТАЛОН ПИСЬМА — РАМКА «3+3»" in seen["prompt"] and "руководителя дирекции AI" in seen["prompt"]
    assert "комментарий, в промпт не идёт" not in seen["prompt"]

    monkeypatch.setattr(ap, "REFERENCE_PATH", tmp_path / "missing.md")
    ap.build_package(vacancy_text="v", title="CIO", package_id="hh_ref2", resume_text="r")
    assert "эталона нет" in seen["prompt"]


@pytest.mark.no_llm
def test_stray_tool_names_trigger_one_retry(ready, monkeypatch):
    with_tools = dict(_LLM_RESPONSE, letter="Добрый день! Внедрял мониторинг (Prometheus/Grafana) и Jira.")
    clean = dict(_LLM_RESPONSE, letter="Добрый день! Внедрял систему мониторинга и трекер задач.")
    calls = []

    def fake(api_key, prompt):
        calls.append(prompt)
        return with_tools if len(calls) == 1 else clean
    monkeypatch.setattr(ap, "_call_llm", fake)

    pkg = ap.build_package(vacancy_text="Нужен CTO, стек не важен", title="CTO", package_id="hh_t1", resume_text="r")
    assert len(calls) == 2 and "Prometheus, Grafana, Jira" in calls[1]
    assert pkg.letter.startswith("Добрый день! Внедрял систему мониторинга")

    calls.clear()
    pkg = ap.build_package(vacancy_text="Стек: Prometheus, Grafana, Jira", title="CTO", package_id="hh_t2", resume_text="r")
    assert len(calls) == 1 and "Prometheus" in pkg.letter          # вакансия называет инструменты — без повтора
    assert ap.stray_tool_names("Zabbix и Loki", "zabbix есть") == ["Loki"]


@pytest.mark.no_llm
def test_tenure_is_twenty_plus():
    assert ap.fix_tenure("Мой профиль: 29 лет в ИТ, 25+ лет в управлении, 129 лет не трогать") \
        == "Мой профиль: 20+ лет в ИТ, 20+ лет в управлении, 129 лет не трогать"
    assert ap.fix_tenure("") == ""


@pytest.mark.no_llm
def test_signature_taken_from_reference():
    ref = "Добрый день!\n\nТекст.\n\nС уважением,\nВячеслав Гришкин\n+7 | mail\nTelegram: @V | Портфель: grishkin.org"
    cut = "Добрый день!\n\nПисьмо.\n\nС уважением,\nВячеслав Гришкин\n+7 | mail"
    out = ap.ensure_signature(cut, ref)
    assert out.endswith("Telegram: @V | Портфель: grishkin.org") and out.startswith("Добрый день!\n\nПисьмо.")
    assert out.count("С уважением,") == 1
    assert ap.ensure_signature("Письмо без подписи", ref).endswith("grishkin.org")
    assert ap.ensure_signature("Письмо", "эталон без подписи") == "Письмо"
    assert ap.ensure_signature("", ref) == ""                      # пустое письмо не маскировать подписью


@pytest.mark.no_llm
def test_old_packages_load_and_retired_keys_are_ignored(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, "OUTPUT_DIR", tmp_path)
    (tmp_path / "hh_1.json").write_text(json.dumps({"package_id": "hh_1", "letter": "Добрый день!",
                                                    "screener_qa": []}), encoding="utf-8")
    pkg = ap.load_saved_package("hh_1")
    assert pkg is not None and pkg.offers == [] and pkg.competencies == [] and pkg.letter == "Добрый день!"

    # пакеты 05.10.2026 с двумя письмами: letter2 / offers2 / letter2_error больше не поля
    old = {"package_id": "hh_2", "letter": "Письмо 1", "letter2": "Письмо 2", "letter2_error": "",
           "offers2": [{"task": "t", "offer": "o", "effect": "e", "proof": ""}],
           "competencies": [{"title": "К", "points": ["п"]}], "screener_qa": []}
    (tmp_path / "hh_2.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    pkg = ap.load_saved_package("hh_2")
    assert pkg is not None and pkg.letter == "Письмо 1" and pkg.competencies[0].title == "К"
    assert not hasattr(pkg, "letter2")


@pytest.mark.no_llm
def test_screener_failure_not_fatal(ready, monkeypatch):
    """Пакет с письмом ценен и без скринера — сбой второго этапа не рушит всё."""
    tmp_path = ready

    def boom(prompt):
        raise RuntimeError("LLM недоступен")
    monkeypatch.setattr(ap, "_call_screener", boom)
    pkg = ap.build_package(vacancy_text="v", package_id="hh_5", resume_text="r")
    assert not pkg.error
    assert pkg.screener_qa == []
    assert (tmp_path / "hh_5.json").exists()


@pytest.mark.no_llm
def test_build_package_facts_in_prompt(ready, monkeypatch):
    """The facts base must reach the LLM prompt."""
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
def test_empty_letter_is_error(ready, monkeypatch):
    tmp_path = ready
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
                                        recommended_variant="cio",
                                        competencies=[ap.Competency(title="К1", points=["п"])],
                                        offers=[ap.Offer(task="т", offer="о", effect="ИТ-стратегия")]),
    )
    client = TestClient(webapp.app)
    resp = client.get("/package/hh/1")
    assert resp.status_code == 200
    assert "Добрый день!" in resp.text and "рамка «3+3»" in resp.text
    assert "Три требования → три доказательства" in resp.text and "ИТ-стратегия" in resp.text
