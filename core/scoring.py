from __future__ import annotations

from core.models import CandidateProfile, Recommendation

WEIGHT_CRITICAL = 3
WEIGHT_IMPORTANT = 2
WEIGHT_TECH = 1

# Score thresholds
THRESHOLD_APPLY = 70
THRESHOLD_CLARIFY = 45

# Penalty per matched negative-industry keyword
INDUSTRY_PENALTY = 15


def _keyword_hits(kw_lower: str, text_lower: str) -> bool:
    """Check if keyword matches text, handling basic Russian morphology via stems."""
    if kw_lower in text_lower:
        return True
    words = kw_lower.split()
    if len(words) == 1:
        # Single word: try trimming last 3 chars (covers most Russian suffixes/endings)
        if len(kw_lower) > 6 and kw_lower[:-3] in text_lower:
            return True
    else:
        # Multi-word: every word (or its stem) must appear in text
        stems = [w[:-3] if len(w) > 6 else w for w in words]
        if all(s in text_lower for s in stems):
            return True
    return False


def find_matches(text: str, keywords: list[str]) -> list[str]:
    text_lower = text.lower()
    return [kw for kw in keywords if _keyword_hits(kw.lower(), text_lower)]


def calculate_score(
    vacancy_text: str,
    profile: CandidateProfile,
) -> tuple[int, list[str], list[str]]:
    """Return (score 0-100, matched_keywords, risk_messages)."""
    critical_matches = find_matches(vacancy_text, profile.skills.critical)
    important_matches = find_matches(vacancy_text, profile.skills.important)
    tech_matches = find_matches(vacancy_text, profile.skills.technologies)

    max_score = (
        len(profile.skills.critical) * WEIGHT_CRITICAL
        + len(profile.skills.important) * WEIGHT_IMPORTANT
        + len(profile.skills.technologies) * WEIGHT_TECH
    )
    raw = (
        len(critical_matches) * WEIGHT_CRITICAL
        + len(important_matches) * WEIGHT_IMPORTANT
        + len(tech_matches) * WEIGHT_TECH
    )

    score = int((raw / max_score) * 100) if max_score > 0 else 0
    score = min(score, 100)

    risks: list[str] = []

    neg_matches = find_matches(vacancy_text, profile.industries_negative)
    if neg_matches:
        score = max(0, score - INDUSTRY_PENALTY * len(neg_matches))
        risks.append(f"Нежелательная отрасль / формат компании: {', '.join(neg_matches)}")

    missing_critical = [kw for kw in profile.skills.critical if kw not in critical_matches]
    if missing_critical:
        sample = ", ".join(missing_critical[:3])
        risks.append(f"Ключевые компетенции не упомянуты в вакансии: {sample}")

    if not vacancy_text.strip() or len(vacancy_text.split()) < 30:
        risks.append("Текст вакансии слишком короткий — возможна неточная оценка")

    # Deduplicate while preserving order (critical → important → tech)
    seen: set[str] = set()
    all_matches: list[str] = []
    for kw in critical_matches + important_matches + tech_matches:
        if kw not in seen:
            seen.add(kw)
            all_matches.append(kw)

    return score, all_matches, risks


def get_recommendation(score: int) -> Recommendation:
    if score >= THRESHOLD_APPLY:
        return Recommendation.APPLY
    if score >= THRESHOLD_CLARIFY:
        return Recommendation.CLARIFY
    return Recommendation.SKIP
