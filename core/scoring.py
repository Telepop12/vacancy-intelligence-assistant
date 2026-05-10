from __future__ import annotations

import re

from core.models import CandidateProfile, Recommendation, ScoringGroup

# Score thresholds
THRESHOLD_APPLY = 70
THRESHOLD_CLARIFY = 45

# Fraction of group keywords that must match for the group to earn full weight.
# Finding fewer yields proportional credit; finding more is capped at 1.0.
_MATCH_THRESHOLD_RATIO = 0.5

_RED_FLAG_MESSAGES: dict[str, str] = {
    "junior_role":      "Вакансия позиционируется для junior/middle специалиста, не для руководителя",
    "hands_on_only":    "Роль предполагает только исполнение без управленческого контура",
    "sales_role":       "Роль сфокусирована на продажах, не на ИТ-управлении",
    "industry_negative": "Нежелательная отрасль / формат компании",
}


# ---------------------------------------------------------------------------
# Keyword matching (handles basic Russian morphology via stem trimming)
# ---------------------------------------------------------------------------

# Hyphen is intentionally absent from boundaries so "ит-стратегии" counts as
# two tokens: "ит" and "стратегии".  This prevents "без" from matching inside
# "кибербезопасности" while still matching compound ИТ-* terms.
_WB_START = r'(?<![а-яёА-ЯЁa-zA-Z0-9])'
_WB_END   = r'(?![а-яёА-ЯЁa-zA-Z0-9])'


def _stem_in_text(stem: str, text: str) -> bool:
    """Match stem with word-boundary awareness.

    Short tokens (≤ 4 chars, e.g. prepositions) must be whole words.
    Longer stems only need a word-start boundary (they're truncated word forms).
    """
    if len(stem) <= 4:
        pattern = _WB_START + re.escape(stem) + _WB_END
    else:
        pattern = _WB_START + re.escape(stem)
    return bool(re.search(pattern, text, re.IGNORECASE))


def _keyword_hits(kw_lower: str, text_lower: str) -> bool:
    if kw_lower in text_lower:
        return True
    words = kw_lower.split()
    if len(words) == 1:
        if len(kw_lower) > 6:
            return _stem_in_text(kw_lower[:-3], text_lower)
    else:
        stems = [w[:-3] if len(w) > 6 else w for w in words]
        return all(_stem_in_text(s, text_lower) for s in stems)
    return False


def find_matches(text: str, keywords: list[str]) -> list[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if _keyword_hits(kw.lower(), text_lower)]


# ---------------------------------------------------------------------------
# Categorical group scoring
# ---------------------------------------------------------------------------

def _group_contribution(vacancy_text: str, group: ScoringGroup) -> tuple[float, list[str]]:
    """Return (points earned, matched keywords) for one scoring group."""
    if not group.keywords:
        return 0.0, []
    matches = find_matches(vacancy_text, group.keywords)
    threshold = max(1, len(group.keywords) * _MATCH_THRESHOLD_RATIO)
    ratio = min(1.0, len(matches) / threshold)
    return group.weight * ratio, matches


def calculate_score(
    vacancy_text: str,
    profile: CandidateProfile,
) -> tuple[int, list[str], list[str]]:
    """Return (score 0-100, matched_keywords, risk_messages)."""
    total_points = 0.0
    seen: set[str] = set()
    all_matches: list[str] = []

    for group in profile.scoring_groups.values():
        pts, group_matches = _group_contribution(vacancy_text, group)
        total_points += pts
        for kw in group_matches:
            if kw not in seen:
                seen.add(kw)
                all_matches.append(kw)

    score = min(100, int(total_points))
    risks = _detect_risks(vacancy_text, profile)
    return score, all_matches, risks


# ---------------------------------------------------------------------------
# Risk / red-flag detection
# ---------------------------------------------------------------------------

def _detect_risks(vacancy_text: str, profile: CandidateProfile) -> list[str]:
    risks: list[str] = []

    for flag_name, keywords in profile.red_flags.items():
        if find_matches(vacancy_text, keywords):
            msg = _RED_FLAG_MESSAGES.get(flag_name, f"Red flag: {flag_name}")
            risks.append(msg)

    if len(vacancy_text.split()) < 30:
        risks.append("Текст вакансии слишком короткий — возможна неточная оценка")

    return risks


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

def get_recommendation(score: int) -> Recommendation:
    if score >= THRESHOLD_APPLY:
        return Recommendation.APPLY
    if score >= THRESHOLD_CLARIFY:
        return Recommendation.CLARIFY
    return Recommendation.SKIP
