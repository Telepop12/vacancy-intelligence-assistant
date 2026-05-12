from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Recommendation(str, Enum):
    APPLY  = "ОТКЛИКАТЬСЯ"
    CLARIFY = "УТОЧНИТЬ"
    LAUNCH = "ЗАПУСТИТЬ В РАБОТУ"   # strategic opportunity, not direct fit
    SKIP   = "ПРОПУСТИТЬ"


@dataclass
class ScoringGroup:
    weight: int
    keywords: list[str] = field(default_factory=list)


@dataclass
class CandidateProfile:
    name: str
    target_roles: list[str]
    scoring_groups: dict[str, ScoringGroup]
    red_flags: dict[str, list[str]]
    seniority_keywords: list[str]


@dataclass
class VacancyAnalysis:
    vacancy_text: str
    analyzed_at: datetime
    match_score: int
    recommendation: Recommendation
    key_matches: list[str]
    risks: list[str]
    hr_questions: list[str]
    hr_response: str
    resume_tips: list[str]
    source_file: str | None = None
    # LLM insight fields — populated by HybridAnalyzer or a real LLM adapter.
    # Empty string means "not computed"; LLM_PENDING means "placeholder".
    role_level_fit: str = ""
    strategic_vs_operational_balance: str = ""
    authority_signals: list[str] = field(default_factory=list)
    target_role_alignment: str = ""
    semantic_summary: str = ""
    # Evolutionary Potential layer
    evolutionary_potential: str = ""           # "High" | "Medium" | "Low"
    strategic_opportunity_signals: list[str] = field(default_factory=list)
    career_strategy_comment: str = ""
    recommended_action: str = ""               # LLM-enhanced final rec (may be LAUNCH)
    # Decision Intelligence layer
    strategic_rationale: str = ""
    career_risks: list[str] = field(default_factory=list)
    career_opportunities: list[str] = field(default_factory=list)
    best_case_scenario: str = ""
    worst_case_scenario: str = ""
    strategic_validation_questions: list[str] = field(default_factory=list)
    # Intake layer — populated by agents/intake.py
    intake_source_type: str = ""
    intake_source_name: str = ""
    intake_confidence: str = ""
    intake_confidence_notes: list[str] = field(default_factory=list)
    intake_detected_title: str = ""
    intake_detected_company: str = ""
    intake_detected_location: str = ""
    intake_detected_salary: str = ""
    intake_url: str = ""
