"""
pytest: загрузчик базы знаний о собеседованиях — офлайн, на реальных файлах
data/interview_kb/ (они в репозитории).
"""
import pytest
import yaml
from datetime import date

from agents import interview_kb as kb

pytestmark = pytest.mark.no_llm


def test_kb_available_and_parsed():
    assert kb.available()
    for key in kb.FILES:
        secs = kb.sections(key)
        assert len(secs) > 10, key
        assert any(s.level == 2 for s in secs) and any(s.level == 3 for s in secs)


def test_find_by_keywords_not_numbers():
    bank = kb.find("stories", "банк вопросов", level=2)
    assert bank is not None and "###" in bank.body          # уровень 2 включает подсекции
    assert kb.find("employers", "что взять в генератор", level=2)
    assert kb.find("search", "первые 100 дней", level=2)
    assert kb.find("search", "кейс-вопросы", level=3)
    assert kb.find("stories", "такого раздела нет") is None


def test_numbered_items_handles_both_list_styles():
    body = ("1. **Раз** начало\n   продолжение\n\n2. Два\n3. Три\n\n"
            "**Специфично:**\n- пункт\n10. уже не список")
    items = kb.numbered_items(body)
    assert items[1] == "**Раз** начало\nпродолжение"
    assert items[2] == "Два" and items[3] == "Три"
    assert 10 not in items


def test_rules_and_patterns_from_real_kb():
    r = kb.rules("employers", 1, 8)
    assert r.startswith("[источник: employers_official.md")
    assert "\n1. " in r or r.count("1. ") >= 1
    assert "8. " in r
    assert kb.rules("employers", 99) == ""
    assert "Негативные маркеры" in kb.patterns(8)


def test_slices_within_budget_and_tagged():
    budgets = [
        (kb.question_bank, 12_000), (kb.stop_words, 10_000), (kb.employer_rules, 8_000),
        (kb.presentation_rules, 6_000), (kb.hundred_days_rules, 5_000),
        (kb.stories_rules, 7_000), (kb.agenda_rules, 8_000), (kb.typical_process, 10_000),
        (kb.improve_rules, 7_000), (kb.team_rules, 7_000),
    ]
    for fn, cap in budgets:
        text = fn()
        assert 500 < len(text) <= cap + 40, fn.__name__
        assert "[источник:" in text, fn.__name__


def test_excerpt_cuts_on_line_boundary():
    text = "\n".join(f"строка {i}" for i in range(200))
    cut = kb.excerpt(text, 300)
    assert cut.endswith("…[выдержка сокращена]")
    assert len(cut) < 340
    assert kb.excerpt("короткий", 300) == "короткий"


@pytest.mark.parametrize("employer,expected,status", [
    ("СберТех", "Сбер", "page"),
    ("ПАО «Сбербанк»", "Сбер", "page"),
    ("Тинькофф", "Т-Банк", "page"),
    ("АО «Т-Банк»", "Т-Банк", "page"),
    ("МТС Диджитал", "МТС", "page"),
    ("ВымпелКом", "Билайн", "page"),
    ("X5 Retail Group", "X5 Group", "page"),
    ("IBS", "IBS", "page"),
    ("Ozon Tech", "Ozon", "blocked"),
    ("Уралхим", "Уралхим", "not_found"),
])
def test_match_company(employer, expected, status):
    assert kb.match_company(employer) == (expected, status)


def test_match_company_unknown_and_word_boundary():
    assert kb.match_company("Топассистент") is None
    assert kb.match_company("Sibsoft") is None      # «ibs» внутри слова — не IBS
    assert kb.match_company("") is None


def test_kb_companies_statuses():
    cos = kb.kb_companies()
    statuses = {s for _n, s in cos}
    assert statuses == {"page", "blocked", "not_found"}
    assert sum(1 for _n, s in cos if s == "page") >= 15
    names = [n for n, _s in cos]
    assert "Билайн" in names and len(names) == len(set(names))


def test_process_profile_company_vs_typical():
    p = kb.process_profile("Т-Банк")
    assert p.status == "page" and p.matched == "Т-Банк"
    assert "Т-Банк" in p.company_text and p.summary
    assert len(kb.process_text(p)) <= 12_500
    assert "публичное описание" in p.status_line

    t = kb.process_profile("Рога и копыта")
    assert t.status == "unknown" and not t.company_text and t.typical_text
    assert "Компании в базе знаний нет" in t.status_line

    n = kb.process_profile("Уралхим")
    assert n.status == "not_found" and "нет" in n.status_line and not n.company_text


def test_sources_index_and_resolve():
    idx = kb.sources_index()
    assert "S18" in idx and "источник 8" in idx
    out = kb.resolve_sources(["real_stories S18", "Danilova (источник 8)", "beelinenow.ru", ""])
    assert len(out) == 3
    assert "Habr" in out[0]
    assert "Данилова" in out[1]
    assert out[2] == "beelinenow.ru"


def test_dont_say_and_version():
    items = kb.dont_say_checklist()
    assert len(items) >= 10
    assert all(text and source for text, source in items)
    assert kb.kb_version() == "2026-09-19"


def test_improve_rules_cover_homework_and_case_bank():
    text = kb.improve_rules()
    assert "Домашняя работа по компании" in text            # employers_official, правило 6
    assert "оптимизируй бизнес-процесс" in text             # правило 5
    assert "Банк кейсов и домашних заданий" in text         # real_stories §4
    assert "S12" in text and "Домашние задания, презентации" in text



def test_team_rules_cover_delegation_and_references():
    text = kb.team_rules()
    assert "руками / делегирую / контролирую" in text            # real_stories, правило 3
    assert "бывших подчинённых" in text                           # референсы у подчинённых
    assert "микроменеджмент" in text and "делегированием" in text  # ассессмент, executive_search 2.3
    assert "Красные флаги" in text and "Кейс-вопросы" in text


def test_numeric_references_match_question_and_sector():
    now = date(2026, 10, 29)
    question = "Бюджет 300 млн, ФОТ 50 процентов: много или мало?"
    medical = kb.quantitative_context(question, "Сеть медицинских клиник", today=now)
    assert all(f"[B{i}]" in medical for i in (1, 2, 3))
    assert "https://" in medical and "NPR" in medical
    assert "Год выборки в открытой карточке не указан" in medical
    other = kb.quantitative_context(question, "Завод промышленного оборудования", today=now)
    assert "[B1]" in other and "[B3]" in other and "[B2]" not in other
    assert kb.quantitative_context("Расскажите о себе", "Сеть клиник, бюджет 300 млн", today=now) == ""
    assert kb.quantitative_context("Фото команды", today=now) == ""
    assert kb.quantitative_context("Как структурировать ответ на собеседовании?", today=now) == ""


@pytest.mark.parametrize("now", [date(2026, 10, 28), date(2027, 4, 30)])
def test_numeric_references_exclude_unreviewed_and_expired(now):
    assert kb.quantitative_context("Бюджет и зарплаты", "Сеть клиник", today=now) == ""


def test_numeric_reference_is_never_cut_before_caveats_or_url():
    args = dict(today=date(2026, 10, 29))
    full = kb.quantitative_context("Бюджет", **args)
    assert full and "https://www.apqc.org/" in full
    assert kb.quantitative_context("Бюджет", max_chars=len(full)-1, **args) == ""


@pytest.mark.parametrize("kind", ["missing", "broken_yaml", "wrong_shape", "no_source", "bad_date"])
def test_numeric_reference_errors_do_not_break_answer(monkeypatch, tmp_path, kind):
    cards = yaml.safe_load((kb.KB_DIR / "benchmarks.yaml").read_text(encoding="utf-8"))
    card = cards[0].copy()
    monkeypatch.setattr(kb, "KB_DIR", tmp_path)
    if kind == "missing":
        pass
    elif kind == "broken_yaml":
        (tmp_path / "benchmarks.yaml").write_text("[invalid", encoding="utf-8")
    else:
        if kind == "no_source":
            card.pop("url")
        if kind == "bad_date":
            card["review_after"] = "unknown"
        content = {"unexpected": 1} if kind == "wrong_shape" else [card]
        (tmp_path / "benchmarks.yaml").write_text(yaml.safe_dump(content), encoding="utf-8")
    assert kb.quantitative_context("Бюджет", today=date(2026, 10, 29)) == ""
