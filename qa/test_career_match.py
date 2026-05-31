"""
pytest: Career Match Layer tests (TC-30..TC-32).
"""
import pytest
from qa.run_functional_tests import (
    tc_career_match_basic,
    tc_career_match_transferable,
    tc_career_match_upgrades_score,
)


@pytest.mark.llm
def test_career_match_basic():
    r = tc_career_match_basic()
    assert r.passed, r.message


@pytest.mark.llm
def test_career_match_transferable():
    r = tc_career_match_transferable()
    assert r.passed, r.message


@pytest.mark.llm
def test_career_match_upgrades_score():
    r = tc_career_match_upgrades_score()
    assert r.passed, r.message


# ---------------------------------------------------------------------------
# Parametrized: arbitration logic (no LLM required)
# ---------------------------------------------------------------------------

@pytest.mark.no_llm
@pytest.mark.parametrize("score,evo,expected_action", [
    (23,  "High",   "ЗАПУСТИТЬ В РАБОТУ"),
    (23,  "Medium", "ПРОПУСТИТЬ"),
    (23,  "Low",    "ПРОПУСТИТЬ"),
    (50,  "High",   "ЗАПУСТИТЬ В РАБОТУ"),
    (50,  "Medium", "УТОЧНИТЬ"),
    (75,  "High",   "ОТКЛИКАТЬСЯ"),   # score >= 70 takes precedence even with evo High
    (75,  "Low",    "ОТКЛИКАТЬСЯ"),
])
def test_recommendation_arbitration(score, evo, expected_action):
    from core.models import Recommendation, VacancyAnalysis
    from datetime import datetime
    from core.recommendation_engine import synthesize

    analysis = VacancyAnalysis(
        vacancy_text="",
        analyzed_at=datetime.now(),
        match_score=score,
        recommendation=Recommendation.APPLY if score >= 70 else (
            Recommendation.CLARIFY if score >= 45 else Recommendation.SKIP
        ),
        key_matches=[],
        risks=[],
        hr_questions=[],
        hr_response="",
        resume_tips=[],
        evolutionary_potential=evo,
        recommended_action=Recommendation.APPLY.value if score >= 70 else (
            Recommendation.CLARIFY.value if score >= 45 else Recommendation.SKIP.value
        ),
    )
    synthesize(analysis)
    assert analysis.recommended_action == expected_action, (
        f"score={score}, evo={evo}: expected {expected_action}, got {analysis.recommended_action}"
    )
