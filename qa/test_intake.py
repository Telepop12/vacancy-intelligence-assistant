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
