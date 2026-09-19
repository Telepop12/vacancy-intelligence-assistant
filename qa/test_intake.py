"""
pytest: Intake & Normalization Layer tests (TC-14..TC-19).
"""
import pytest
from qa.run_functional_tests import (
    tc_intake_text_source,
    tc_intake_file_source,
    tc_intake_html_normalization,
    tc_intake_broken_json,
    tc_intake_missing_title,
    tc_intake_low_confidence_short,
)


@pytest.mark.no_llm
def test_intake_text_source():
    r = tc_intake_text_source()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_intake_file_source():
    r = tc_intake_file_source()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_intake_html_normalization():
    r = tc_intake_html_normalization()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_intake_broken_json():
    r = tc_intake_broken_json()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_intake_missing_title():
    r = tc_intake_missing_title()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_intake_low_confidence_short():
    r = tc_intake_low_confidence_short()
    assert r.passed, r.message


# ---------------------------------------------------------------------------
# Parametrized: intake confidence levels
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
@pytest.mark.parametrize("text,expected_not", [
    ("", "HIGH"),
    ("ИТ специалист нужен срочно", "HIGH"),
    ("Ищем сотрудника. Опыт от 1 года. Зарплата обсуждается.", "HIGH"),
])
def test_intake_confidence_not_high_for_short_texts(text, expected_not):
    from agents.intake import from_text
    vi = from_text(text)
    assert vi.intake_confidence.value != expected_not, (
        f"Expected confidence != {expected_not} for short text, got {vi.intake_confidence.value}"
    )


@pytest.mark.no_llm
@pytest.mark.parametrize("source,expected_level", [
    ("<p>test</p>", "html"),
    ('{"title": "CTO"}', "json"),
])
def test_intake_source_type_detected(source, expected_level):
    from agents.intake import from_html, from_json
    fn = from_html if expected_level == "html" else from_json
    vi = fn(source)
    assert vi.source_type.value == expected_level


# --- Зарплата: явное поле hh важнее эвристики, HTML-списки не склеиваются ---

_HH_HTML = ("<p><strong>Условия:</strong></p><ul><li>Конкурентная зарплата</li>"
            "<li>Новое оборудование Apple и Корпоративная симкарта</li>"
            "<li>Полная занятость согласно ТК</li></ul>")


@pytest.mark.no_llm
def test_from_json_explicit_none_salary_beats_text_heuristic():
    from agents.intake import from_json
    vi = from_json({"name": "Head of IT", "employer": "School", "area": "Москва",
                    "salary": None, "description": _HH_HTML, "hh_id": "1"})
    assert vi.salary == ""
    # блочные теги стали переводами строк — пункты списка не склеены
    lines = vi.normalized_text.splitlines()
    assert "Конкурентная зарплата" in lines
    assert "Новое оборудование Apple и Корпоративная симкарта" in lines


@pytest.mark.no_llm
def test_from_json_salary_dict_and_string():
    from agents.intake import from_json
    vi = from_json({"name": "CIO", "salary": {"from": 300000, "to": 400000, "currency": "RUR"},
                    "description": "Обязанности: ИТ-стратегия."})
    assert vi.salary == "от 300000 до 400000 RUR"
    vi = from_json({"name": "CIO", "salary": "от 500 000 &#8381;",
                    "description": "Обязанности: ИТ-стратегия."})
    assert vi.salary == "от 500 000 ₽"


@pytest.mark.no_llm
@pytest.mark.parametrize("text,expected", [
    ("Зарплата: от 300 000 руб. на руки", "от 300 000 руб. на руки"),
    ("Зарплата от 190 000 до 250 000 ₽", "от 190 000 до 250 000 ₽"),
    ("Salary: 15,000 AED", "15,000 AED"),
    ("Условия: Конкурентная зарплата Новое оборудование Apple", ""),
    ("Команда из 10 компаний и 3 команды разработчиков", ""),
    ("Оклад 250 тыс. + бонус", "250 тыс. + бонус"),
    ("Вилка 300–500 тыс. ₽ net в месяц", "300–500 тыс. ₽ net в месяц"),
    ("Площадь 300 тыс. кв м, 700 тыс. клиентов, 100k+ пользователей", ""),
    ("Офис: ул. Ленина, 146к2, корпус 32 к 1", ""),
    ("Компенсация питания 500 рублей в день", ""),
])
def test_salary_heuristic(text, expected):
    from agents.intake import _first_match, _SALARY_RE
    assert _first_match(_SALARY_RE, text) == expected
