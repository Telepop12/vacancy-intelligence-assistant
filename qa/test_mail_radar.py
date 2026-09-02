"""
pytest: Mail Radar — разбор рассылок LinkedIn/hh, дедуп, триаж hh-лидов.
Всё офлайн: сеть и файлы состояния замоканы.
"""
import pytest

from agents import hh_api, hh_search, mail_radar, vacancy_store
from agents.mail_radar import (
    STATUS_CONVERTED, STATUS_ERROR, STATUS_HIDDEN, STATUS_NEW, STATUS_TRIAGED,
    detect_source, ingest_emails, parse_hh_body, parse_linkedin_body,
    variant_from_subject,
)
from core.models import CandidateProfile, ScoringGroup


# ---------------------------------------------------------------------------
# Фикстуры: усечённые тела реальных писем (02.09.2026)
# ---------------------------------------------------------------------------

_LI_SENDER = "Оповещения о вакансиях LinkedIn <jobalerts-noreply@linkedin.com>"
_LI_SUBJECT = "Head of Enterprise Applications & Transformation в компании Etihad"
_LI_BODY = """Ваше оповещение о вакансиях «Глава офиса управления портфелем проектов» в регионе Объединённые Арабские Эмираты

Новые вакансии, соответствующие Вашим предпочтениям.

Head of Enterprise Applications & Transformation
Etihad
Абу-Даби

Эта компания активно нанимает новых сотрудников
Подайте заявку, загрузив свое резюме и сведения профиля
См. вакансию: https://www.linkedin.com/comm/jobs/view/4450457874/?trackingId=abc&refId=xyz

---------------------------------------------------------

Director, Technology Program Management
Ladders
Соединённые Штаты Америки
Зарплата от 190 тыс. $ до 304 тыс. $ в год

Эта компания активно нанимает новых сотрудников
См. вакансию: https://www.linkedin.com/comm/jobs/view/4460066246/?trackingId=def

---------------------------------------------------------

См. все вакансии в LinkedIn: https://www.linkedin.com/comm/jobs/search-results/?keywords=x

Выполняйте поиск вакансий эффективнее с помощью Premium
https://www.linkedin.com/comm/premium/products/?upsell=1
"""

# Дайджест с одной вакансией: LinkedIn пишет служебную строку в единственном числе
_LI_SINGLE_BODY = """Ваше оповещение о вакансиях «Глава офиса управления портфелем проектов» в регионе Соединенные Штаты Америки

Новая вакансия, соответствующая Вашим предпочтениям.

Senior Delivery Manager cum Portfolio Manager
HTC Global Services
Соединенные Штаты Америки

Эта компания активно нанимает новых сотрудников
См. вакансию: https://www.linkedin.com/comm/jobs/view/4470000001/?trackingId=ghi

---------------------------------------------------------

См. все вакансии в LinkedIn: https://www.linkedin.com/comm/jobs/search-results/?keywords=x
"""

_HH_SENDER = "noreply@hh.ru"
_HH_SUBJECT = ("Подходящие вакансии для резюме: "
               "«Технический директор (разработка и проектное управление)»")
_HH_BODY = """ Письмо

| От проверенных работодателей |

| Новые вакансии для вашего резюме |

| Директор проектного офиса/Заместитель Генерального директора[](https://hh.ru/vacancy/136567950?utm_source=email&utm_campaign=vacancies_selected&utm_content=vacancy_name&loginkey=abc) |

| |
| Датаюниверс |

| |
| Посмотреть вакансию [](https://hh.ru/vacancy/136567950?utm_source=email&utm_content=butt&loginkey=abc) |

| Директор по программным продуктам экосистемы Kvadra[](https://hh.ru/vacancy/136793498?utm_content=vacancy_name&loginkey=abc) |

| |
| YADRO |

| |
| Посмотреть вакансию [](https://hh.ru/vacancy/136793498?utm_content=butt&loginkey=abc) |

| Все подходящие вакансии [](https://hh.ru/search/vacancy?resume=x&utm_content=butt_all) |
"""


def _emails() -> list[dict]:
    return [
        {"sender": _LI_SENDER, "subject": _LI_SUBJECT,
         "date": "2026-09-02T07:32:07Z", "body": _LI_BODY},
        {"sender": _HH_SENDER, "subject": _HH_SUBJECT,
         "date": "2026-09-02T06:24:28Z", "body": _HH_BODY},
    ]


def _profile() -> CandidateProfile:
    return CandidateProfile(
        name="Тест",
        target_roles=["CIO"],
        scoring_groups={"core": ScoringGroup(weight=100, keywords=["ИТ-стратегия"])},
        red_flags={},
        seniority_keywords=[],
    )


def _hh_intake(vid: str) -> dict:
    return {
        "name": f"Вакансия {vid}",
        "employer": "Работодатель",
        "area": "Москва",
        "salary": None,
        "alternate_url": f"https://hh.ru/vacancy/{vid}",
        "published_at": "2026-09-02",
        "hh_id": vid,
        "description": ("Обязанности: разработка ИТ-стратегия компании. "
                        "Требования: опыт руководства. Условия: офис."),
    }


def _fetch_ok(ids):
    return {vid: _hh_intake(vid) for vid in ids}, {}, False


@pytest.fixture()
def _isolated_state(monkeypatch, tmp_path):
    monkeypatch.setattr(mail_radar, "STATE_PATH", tmp_path / "radar.json")
    monkeypatch.setattr(hh_search, "STATE_PATH", tmp_path / "search.json")
    monkeypatch.setattr(vacancy_store, "STORE_DIR", tmp_path / "store")
    # Реальный output/hh_cooldown.json не должен влиять на тесты
    monkeypatch.setattr(hh_api, "_COOLDOWN_PATH", tmp_path / "cooldown.json")


# ---------------------------------------------------------------------------
# Определение источника и варианта резюме
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
def test_detect_source():
    assert detect_source(_LI_SENDER, _LI_SUBJECT) == "linkedin"
    assert detect_source(_HH_SENDER, _HH_SUBJECT) == "hh"
    # hh без маркера в теме — не рассылка вакансий (например, чек-письмо)
    assert detect_source("noreply@hh.ru", "Ваше резюме просмотрено") == ""
    assert detect_source("boss@example.com", "Привет") == ""
    # Фолбэк по телу для пересланных писем
    assert detect_source("", "", _LI_BODY) == "linkedin"


@pytest.mark.no_llm
@pytest.mark.parametrize("subject,expected", [
    (_HH_SUBJECT, "CTO"),
    ("Подходящие вакансии для резюме: «Руководитель по информационным технологиям (CIO)»", "CIO"),
    ("Подходящие вакансии для резюме: «Директор по информационным технологиям (CIO)»", "CIO"),
    ("Подходящие вакансии для резюме: «Руководитель по цифровой трансформации / "
     "Управлению данными / AI интеграции  (CDO, CAIO, CDTO)»", "CDO"),
    ("Что-то нерелевантное", ""),
])
def test_variant_from_subject(subject, expected):
    assert variant_from_subject(subject) == expected


# ---------------------------------------------------------------------------
# Парсеры
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
def test_parse_linkedin_body():
    leads = parse_linkedin_body(_LI_BODY, email_date="2026-09-02", subject=_LI_SUBJECT)
    assert [l.ext_id for l in leads] == ["4450457874", "4460066246"]

    first = leads[0]
    assert first.title == "Head of Enterprise Applications & Transformation"
    assert first.company == "Etihad"
    assert first.location == "Абу-Даби"
    assert first.url == "https://www.linkedin.com/jobs/view/4450457874/"
    assert first.source == "linkedin"
    assert first.email_date == "2026-09-02"

    second = leads[1]
    assert second.company == "Ladders"
    assert second.salary.startswith("Зарплата от 190")


@pytest.mark.no_llm
def test_parse_linkedin_single_vacancy_digest():
    """Служебная строка в единственном числе не должна стать названием."""
    leads = parse_linkedin_body(_LI_SINGLE_BODY)
    assert len(leads) == 1
    assert leads[0].title == "Senior Delivery Manager cum Portfolio Manager"
    assert leads[0].company == "HTC Global Services"


_HH_BODY_SALARY = """| Корпоративный архитектор B2E ассистента[](https://hh.ru/vacancy/137000001?utm_content=vacancy_name&loginkey=abc) |

| |
| от 500 000 ₽ за месяц |

| |
| Компания &quot;Цивилизация&quot; |

| |
| Посмотреть вакансию [](https://hh.ru/vacancy/137000001?utm_content=butt&loginkey=abc) |
"""


@pytest.mark.no_llm
def test_parse_hh_body_salary_cell_is_not_company():
    leads = parse_hh_body(_HH_BODY_SALARY, subject=_HH_SUBJECT)
    assert len(leads) == 1
    assert leads[0].salary == "от 500 000 ₽ за месяц"
    assert leads[0].company == 'Компания "Цивилизация"'


@pytest.mark.no_llm
def test_from_json_unescapes_hh_entities():
    from agents.intake import from_json
    vi = from_json({"name": "Директор по развитию в компанию &quot;Civilizatia&quot;",
                    "employer": "Айона &amp; Эстейт", "description": "x" * 400})
    assert vi.title == 'Директор по развитию в компанию "Civilizatia"'
    assert vi.company == "Айона & Эстейт"


@pytest.mark.no_llm
def test_parse_hh_body():
    leads = parse_hh_body(_HH_BODY, email_date="2026-09-02", subject=_HH_SUBJECT)
    assert [l.ext_id for l in leads] == ["136567950", "136793498"]

    first = leads[0]
    assert first.title == "Директор проектного офиса/Заместитель Генерального директора"
    assert first.company == "Датаюниверс"
    assert first.url == "https://hh.ru/vacancy/136567950"
    assert first.resume_variant == "CTO"

    assert leads[1].title == "Директор по программным продуктам экосистемы Kvadra"
    assert leads[1].company == "YADRO"


# ---------------------------------------------------------------------------
# Ingest: новые лиды, дедуп, триаж hh
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
def test_ingest_and_dedupe(monkeypatch, _isolated_state):
    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", _fetch_ok)

    report = ingest_emails(_emails(), _profile())
    assert report.emails_parsed == 2
    assert report.new_linkedin == 2
    assert report.new_hh == 2
    assert report.triaged_hh == 2
    assert report.duplicates == 0

    # hh-вакансии попали в общий триаж с пометкой источника и варианта
    rec = hh_search.get_state_item("136567950")
    assert rec is not None
    assert rec["source"] == "mail:hh"
    assert rec["resume_variant"] == "CTO"

    # LinkedIn-лиды ждут решения
    li = mail_radar.linkedin_leads()
    assert len(li) == 2
    assert all(r["status"] == STATUS_NEW for r in li)

    # Повторная передача тех же писем: они пропускаются, счётчики не растут,
    # сеть не трогаем
    def _no_fetch(ids):
        raise AssertionError("fetch не должен вызываться повторно")
    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", _no_fetch)

    report2 = ingest_emails(_emails(), _profile())
    assert report2.emails_skipped == 2
    assert report2.emails_parsed == 0
    assert report2.duplicates == 0
    assert report2.new_linkedin == 0 and report2.new_hh == 0
    assert mail_radar.load_state()["leads"]["linkedin:4450457874"]["times_seen"] == 1

    # Та же вакансия в НОВОМ письме (другая дата) — это честный повтор
    again = {"sender": _LI_SENDER, "subject": _LI_SUBJECT,
             "date": "2026-09-03T07:32:07Z", "body": _LI_BODY}
    report3 = ingest_emails([again], _profile())
    assert report3.emails_parsed == 1
    assert report3.duplicates == 2
    lead = mail_radar.load_state()["leads"]["linkedin:4450457874"]
    assert lead["times_seen"] == 2
    assert lead["last_seen"] >= lead["first_seen"]


@pytest.mark.no_llm
def test_ingest_hh_error_retried(monkeypatch, _isolated_state):
    # Запуск 1: hh недоступен — лиды падают в error, но не считаются увиденными
    monkeypatch.setattr(
        hh_api, "fetch_vacancies_batch",
        lambda ids: ({}, {vid: "hh.ru вернул HTTP 403" for vid in ids}, True),
    )
    report = ingest_emails(_emails(), _profile())
    assert report.triaged_hh == 0
    assert any("ограничил частоту" in e for e in report.errors)
    assert mail_radar.load_state()["leads"]["hh:136567950"]["status"] == STATUS_ERROR

    # Запуск 2: hh ожил — письма уже разобраны, но незагруженные вакансии
    # всё равно повторяются (независимо от писем)
    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", _fetch_ok)
    report2 = ingest_emails(_emails(), _profile())
    assert report2.emails_skipped == 2
    assert report2.triaged_hh == 2
    assert mail_radar.load_state()["leads"]["hh:136567950"]["status"] == STATUS_TRIAGED
    assert hh_search.get_state_item("136793498")["source"] == "mail:hh"


@pytest.mark.no_llm
def test_ingest_respects_hh_cooldown(monkeypatch, _isolated_state):
    """Пока hh «остывает», сеть не трогаем — иначе кулдаун только продлевается."""
    monkeypatch.setattr(hh_api, "_cooldown_left", lambda: 12)

    def _no_fetch(ids):
        raise AssertionError("fetch не должен вызываться во время кулдауна")
    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", _no_fetch)

    report = ingest_emails(_emails(), _profile())
    assert report.new_hh == 2 and report.triaged_hh == 0
    assert any("на паузе" in e for e in report.errors)
    lead = mail_radar.load_state()["leads"]["hh:136567950"]
    assert lead["status"] == STATUS_ERROR
    assert "12 мин" in lead["error"]


@pytest.mark.no_llm
def test_ingest_per_run_fetch_cap(monkeypatch, _isolated_state):
    monkeypatch.setattr(mail_radar, "MAX_HH_FETCH_PER_RUN", 1)
    fetched_batches: list[list[str]] = []

    def _fetch(ids):
        fetched_batches.append(list(ids))
        return _fetch_ok(ids)
    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", _fetch)

    report = ingest_emails(_emails(), _profile())
    assert fetched_batches == [["136567950"]]
    assert report.triaged_hh == 1
    assert any("Отложено" in e for e in report.errors)

    # Следующий прогон (даже без писем) добирает отложенное
    report2 = ingest_emails([], _profile())
    assert fetched_batches[-1] == ["136793498"]
    assert report2.triaged_hh == 1


@pytest.mark.no_llm
def test_lead_lifecycle(monkeypatch, _isolated_state):
    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", _fetch_ok)
    ingest_emails(_emails(), _profile())

    # Скрыть / вернуть
    assert mail_radar.set_lead_status("linkedin:4450457874", STATUS_HIDDEN)
    assert len(mail_radar.linkedin_leads()) == 1
    assert mail_radar.set_lead_status("linkedin:4450457874", STATUS_NEW)
    assert len(mail_radar.linkedin_leads()) == 2
    assert not mail_radar.set_lead_status("linkedin:нет-такого", STATUS_HIDDEN)

    # Ручное добавление текста по ссылке лида закрывает лид
    mail_radar.mark_converted_by_url("https://www.linkedin.com/jobs/view/4450457874/", "m20260902")
    lead = mail_radar.load_state()["leads"]["linkedin:4450457874"]
    assert lead["status"] == STATUS_CONVERTED
    assert lead["vid"] == "m20260902"
    assert len(mail_radar.linkedin_leads()) == 1


@pytest.mark.no_llm
def test_mail_triage_rows_filter(monkeypatch, _isolated_state):
    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", _fetch_ok)
    ingest_emails(_emails(), _profile())
    # Вакансия из обычного поиска не должна попадать в почтовый список
    hh_search.register_vacancy(_profile(), _hh_intake("999001"), "999001")

    rows = mail_radar.mail_triage_rows()
    ids = {r["hh_id"] for r in rows}
    assert ids == {"136567950", "136793498"}


# ---------------------------------------------------------------------------
# Актуальность LinkedIn-лидов (публичная страница вакансии)
# ---------------------------------------------------------------------------

def _li_page(closed: bool) -> str:
    """Гостевая страница вакансии LinkedIn в миниатюре (реальные маркеры 02.09.2026)."""
    flavor = ('<figure class="closed-job closed-job__flavor topcard__flavor-row">'
              '<figcaption class="closed-job__flavor--closed">'
              'Заявки на эту вакансию больше не принимаются</figcaption></figure>'
              if closed else "")
    return ("<html><head><title>Компания Etihad нанимает</title></head><body>"
            "<h1 class=\"top-card-layout__title\">Head of Enterprise Applications</h1>"
            + flavor + "<div>" + "x" * 25_000 + "</div></body></html>")


@pytest.mark.no_llm
def test_linkedin_page_status():
    assert mail_radar.linkedin_page_status(_li_page(closed=True)) == "closed"
    assert mail_radar.linkedin_page_status(_li_page(closed=False)) == "open"
    assert mail_radar.linkedin_page_status(_li_page(False), "https://www.linkedin.com/authwall?x=1") == "blocked"
    assert mail_radar.linkedin_page_status("<html>stub</html>") == "blocked"
    # Удалённая вакансия (HTTP 404) — закрыта, а не ошибка
    assert mail_radar.linkedin_page_status("", mail_radar.LI_GONE) == "closed"


@pytest.mark.no_llm
def test_fetch_linkedin_404_means_gone(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    def _raise_404(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))
    monkeypatch.setattr(urllib.request, "urlopen", _raise_404)
    assert mail_radar.fetch_linkedin_page("https://www.linkedin.com/jobs/view/1/") == ("", mail_radar.LI_GONE)


@pytest.mark.no_llm
def test_check_linkedin_leads(monkeypatch, _isolated_state):
    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", _fetch_ok)
    ingest_emails(_emails(), _profile())
    # Дата письма делает лид «старым» для второго вызова — проверяем возраст
    older = mail_radar.load_state()
    older["leads"]["linkedin:4460066246"]["email_date"] = "2026-08-01"
    mail_radar.save_state(older)

    pages = {
        "https://www.linkedin.com/jobs/view/4450457874/": _li_page(closed=True),
        "https://www.linkedin.com/jobs/view/4460066246/": _li_page(closed=False),
    }
    calls: list[str] = []

    def _fetch(url):
        calls.append(url)
        return pages[url], url

    rep = mail_radar.check_linkedin_leads(fetch=_fetch, sleep=lambda: None)
    assert rep.checked == 2 and rep.closed == 1 and rep.still_open == 1
    assert rep.left_unchecked == 0 and not rep.stopped
    assert len(calls) == 2

    state = mail_radar.load_state()
    assert state["leads"]["linkedin:4450457874"]["status"] == "closed"
    assert state["leads"]["linkedin:4460066246"]["status"] == STATUS_NEW
    assert state["leads"]["linkedin:4460066246"]["checked_at"]

    # Закрытая ушла из активного списка, возраст посчитан по дате письма
    active = mail_radar.linkedin_leads()
    assert [r["ext_id"] for r in active] == ["4460066246"]
    assert active[0]["age_days"] > mail_radar.FRESH_DAYS


@pytest.mark.no_llm
def test_check_linkedin_stops_on_block(monkeypatch, _isolated_state):
    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", _fetch_ok)
    ingest_emails(_emails(), _profile())

    def _blocked(url):
        raise mail_radar.LinkedInBlocked("LinkedIn ограничил доступ (HTTP 999)")

    rep = mail_radar.check_linkedin_leads(fetch=_blocked, sleep=lambda: None)
    assert rep.checked == 0 and rep.stopped.startswith("LinkedIn ограничил")
    assert rep.left_unchecked == 2
    # Ничего не помечено — проверим в следующий раз
    assert all(r["status"] == STATUS_NEW for r in mail_radar.linkedin_leads())
