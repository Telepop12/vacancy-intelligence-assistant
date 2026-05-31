"""
pytest: Resume Intelligence Layer tests (TC-20..TC-29).
"""
import pytest
from qa.run_functional_tests import (
    tc_resume_large_cv,
    tc_resume_ai_signals,
    tc_resume_trajectory,
    tc_resume_weak_ai_positioning,
    tc_resume_strong_transformation,
    tc_resume_enterprise_scale,
    tc_resume_operational_framing,
    tc_resume_no_false_telecom,
    tc_resume_executive_language,
    tc_resume_hidden_ai,
)


@pytest.mark.no_llm
def test_resume_large_cv():
    r = tc_resume_large_cv()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_resume_ai_signals():
    r = tc_resume_ai_signals()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_resume_trajectory():
    r = tc_resume_trajectory()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_resume_weak_ai_positioning():
    r = tc_resume_weak_ai_positioning()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_resume_strong_transformation():
    r = tc_resume_strong_transformation()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_resume_enterprise_scale():
    r = tc_resume_enterprise_scale()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_resume_operational_framing():
    r = tc_resume_operational_framing()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_resume_no_false_telecom():
    r = tc_resume_no_false_telecom()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_resume_executive_language():
    r = tc_resume_executive_language()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_resume_hidden_ai():
    r = tc_resume_hidden_ai()
    assert r.passed, r.message


# ---------------------------------------------------------------------------
# Parametrized: evolutionary potential detection (new rule-based detector)
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
@pytest.mark.parametrize("text,expected_level", [
    # AI CoE vacancy with CEO/board access → High
    (
        "Прямое подчинение CEO. Создание AI CoE с нуля. "
        "Участие в совете директоров. AI roadmap. Измеримый ROI.",
        "High",
    ),
    # Regular helpdesk → Low
    (
        "Технический специалист. Поддержка пользователей. "
        "Help Desk 1 линия. Администрирование Windows.",
        "Low",
    ),
    # Partial signals → Medium (digital transformation + cross-functional, but no CEO/board/AI CoE)
    (
        "Руководитель ИТ-отдела. Цифровая трансформация предприятия. "
        "Кросс-функциональное взаимодействие со всеми подразделениями.",
        "Medium",
    ),
])
def test_evolutionary_potential_rule_based(text, expected_level):
    from core.scoring import detect_evolutionary_potential
    level, _ = detect_evolutionary_potential(text)
    assert level == expected_level, f"Expected {expected_level}, got {level} for: {text[:60]}"


@pytest.mark.no_llm
@pytest.mark.parametrize("period,idx,expected_level", [
    ("2020 – н.в.", 0, "current"),    # current role
    ("2020 – 2024", 0, "high"),       # recent (2 years ago)
    ("2010 – 2014", 3, "medium"),     # 12 years ago
    ("2000 – 2005", 5, "context"),    # 21 years ago
])
def test_role_recency_weight(period, idx, expected_level):
    from agents.resume_intelligence import _role_recency_weight
    weight = _role_recency_weight(period, idx).lower()
    level_markers = {
        "current": ["текущая"],
        "high":    ["высокий"],
        "medium":  ["средний"],
        "context": ["контекст"],
    }
    markers = level_markers[expected_level]
    assert any(m in weight for m in markers), (
        f"Period '{period}' idx={idx}: expected level '{expected_level}', got label: {weight}"
    )
