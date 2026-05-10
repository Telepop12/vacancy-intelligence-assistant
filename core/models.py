from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Recommendation(str, Enum):
    APPLY = "ОТКЛИКАТЬСЯ"
    CLARIFY = "УТОЧНИТЬ"
    SKIP = "ПРОПУСТИТЬ"


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
