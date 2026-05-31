"""
pytest: Vacancy analysis tests (TC-01..TC-13).
Wraps legacy test functions from run_functional_tests.py.
"""
import pytest
from qa.run_functional_tests import (
    tc_file_input,
    tc_stdin_pipe,
    tc_interactive_simulated,
    tc_markdown_report,
    tc_json_report,
    tc_registry_updated,
    tc_strong_vacancy,
    tc_weak_vacancy,
    tc_ai_partner_vacancy,
    tc_evolutionary_launch,
    tc_di_launch_has_rationale,
    tc_di_clarify_has_risks_and_opportunities,
    tc_di_apply_has_scenarios,
)


@pytest.mark.no_llm
def test_file_input():
    r = tc_file_input()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_stdin_pipe():
    r = tc_stdin_pipe()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_interactive_simulated():
    r = tc_interactive_simulated()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_markdown_report():
    r = tc_markdown_report()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_json_report():
    r = tc_json_report()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_registry_updated():
    r = tc_registry_updated()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_strong_vacancy():
    r = tc_strong_vacancy()
    assert r.passed, r.message


@pytest.mark.no_llm
def test_weak_vacancy():
    r = tc_weak_vacancy()
    assert r.passed, r.message


@pytest.mark.llm
def test_ai_partner_vacancy():
    r = tc_ai_partner_vacancy()
    assert r.passed, r.message


@pytest.mark.llm
def test_evolutionary_launch():
    r = tc_evolutionary_launch()
    assert r.passed, r.message


@pytest.mark.llm
def test_di_launch_has_rationale():
    r = tc_di_launch_has_rationale()
    assert r.passed, r.message


@pytest.mark.llm
def test_di_clarify_has_risks_and_opportunities():
    r = tc_di_clarify_has_risks_and_opportunities()
    assert r.passed, r.message


@pytest.mark.llm
def test_di_apply_has_scenarios():
    r = tc_di_apply_has_scenarios()
    assert r.passed, r.message
