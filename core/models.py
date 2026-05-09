from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Recommendation(str, Enum):
    APPLY = "ОТКЛИКАТЬСЯ"
    CLARIFY = "УТОЧНИТЬ"
    SKIP = "ПРОПУСТИТЬ"


@dataclass
class SkillGroup:
    critical: list[str] = field(default_factory=list)
    important: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)


@dataclass
class CandidateProfile:
    name: str
    target_roles: list[str]
    skills: SkillGroup
    industries_preferred: list[str]
    industries_negative: list[str]
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
