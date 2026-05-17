"""
Career Match Layer — Resume-Aware Vacancy Analysis.

Implements Option B (parallel layer):
  - Keyword score: deterministic, always available
  - Career Match Score: LLM-judged, available when ResumeProfile exists

Unlike keyword scoring, this layer analyses the full career trajectory,
transferable competencies, and hidden relevance — not just keyword overlap.

Flow:
    VacancyInput + ResumeProfile → career_match() → CareerMatchResult
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.intake import VacancyInput
from agents.resume_intelligence import ResumeProfile


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

@dataclass
class CareerMatchResult:
    """Combined scoring: keyword (deterministic) + career match (LLM-judged)."""
    # Scores
    keyword_score:      int = 0     # from RuleBasedAnalyzer
    keyword_rec:        str = ""    # ОТКЛИКАТЬСЯ / УТОЧНИТЬ / ПРОПУСТИТЬ
    career_match_score: int = 0     # LLM holistic assessment (0–100)

    # LLM analysis
    executive_summary:          str = ""
    trajectory_analysis:        str = ""
    transferable_competencies:  list[str] = field(default_factory=list)
    strategic_strengths:        list[str] = field(default_factory=list)
    risks_and_gaps:             list[str] = field(default_factory=list)
    final_recommendation:       str = ""
    recommendation_label:       str = ""  # ОТКЛИКАТЬСЯ/УТОЧНИТЬ/ЗАПУСТИТЬ В РАБОТУ/ПРОПУСТИТЬ

    # Meta
    analysis_timestamp: datetime = field(default_factory=datetime.now)
    confidence_notes:   list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# System prompt — user-provided expert framing
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Ты — эксперт по оценке кандидатов уровня Executive и Top Management, специализирующийся на ролях:
CIO / CTO / CISO / AI Transformation / Digital Transformation / Enterprise IT Leadership /
Technology Strategy / Innovation Management / Organizational Transformation.

Твоя задача — НЕ выполнять примитивный ATS-анализ и НЕ ограничиваться поиском ключевых слов.

Ты анализируешь:
- карьерную траекторию кандидата целиком, а не только последнее место
- переносимые (transferable) компетенции
- эволюцию управленческих и стратегических навыков
- масштаб и сложность реализованных задач
- уровень организационной ответственности
- скрытую релевантность предыдущего опыта

Правила взвешивания опыта:
- Свежий опыт важнее, но исторический сохраняет ценность если связан с трансформацией,
  стратегическим управлением, enterprise-архитектурой, PMO, M&A, инновациями
- Лидерские и трансформационные компетенции устаревают медленно
- Узкоспециализированные технические навыки — быстрее
- Не штрафуй за нелинейную карьеру если сохраняется рост масштаба ответственности
- Мультидоменный опыт = преимущество при единой логике развития компетенций

Логика transferable competencies:
интеграция ИТ-сервисов → M&A интеграция → организационная трансформация
управление инфраструктурой → enterprise systems thinking → устойчивость процессов
DevOps / автоматизация → системное повышение операционной эффективности
кибербезопасность → governance и управление рисками
архитектурный опыт → системное мышление → проектирование enterprise-изменений

Отвечай строго в формате JSON без лишнего текста. Все строковые значения — на русском языке."""

_USER_TEMPLATE = """\
Резюме кандидата:
---
{resume_text}
---

Вакансия:
---
{vacancy_text}
---

Контекст keyword-анализа:
- Keyword match score: {keyword_score}/100 (детерминированный)
- Rule-based рекомендация: {keyword_rec}

Контекст resume intelligence:
- Архетип: {archetype} · Стаж: ~{years} лет · Масштаб: {scale}
- Домены: {domains}
- AI signals: {ai_count} · Трансформация: {tf_count}
- Executive framing: {framing_level} ({framing_score}/100)
- Сильные стороны: {strengths}
- Weak visibility: {weak_vis}

Верни ТОЛЬКО валидный JSON (без markdown):
{{
  "career_match_score": 0-100,
  "executive_summary": "2-3 предложения: как карьера кандидата соответствует вакансии стратегически",
  "trajectory_analysis": "2-3 предложения: эволюция компетенций и релевантность полной карьерной траектории",
  "transferable_competencies": [
    "конкретная компетенция + откуда она и почему релевантна вакансии"
  ],
  "strategic_strengths": [
    "конкретная сила кандидата применительно к данной вакансии"
  ],
  "risks_and_gaps": [
    "реалистичный риск или пробел"
  ],
  "final_recommendation": "1-2 предложения итогового заключения как executive-рекрутер",
  "recommendation_label": "ОТКЛИКАТЬСЯ|УТОЧНИТЬ|ЗАПУСТИТЬ В РАБОТУ|ПРОПУСТИТЬ"
}}

career_match_score логика:
- Учитывает всю карьеру, а не только keyword overlap
- 70+ = явное стратегическое соответствие
- 50-69 = значимый transferable fit с уточнениями
- 30-49 = потенциал есть, но требует валидации
- <30 = существенные риски несоответствия

recommendation_label:
- ОТКЛИКАТЬСЯ: career_match_score ≥ 70
- ЗАПУСТИТЬ В РАБОТУ: score 45-69 с высоким transferable потенциалом
- УТОЧНИТЬ: смешанные сигналы, нужны уточнения
- ПРОПУСТИТЬ: низкий career fit без компенсирующих факторов

transferable_competencies — 3-5 конкретных пунктов с объяснением связи
strategic_strengths — 3-5 применительно именно к данной вакансии
risks_and_gaps — честно, 2-3 реалистичных ограничения"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def career_match(
    vacancy: VacancyInput,
    resume: ResumeProfile,
    keyword_score: int = 0,
    keyword_rec: str = "",
) -> CareerMatchResult:
    """
    Run resume-aware career match analysis.
    Returns CareerMatchResult with both keyword_score and career_match_score.
    Degrades gracefully if LLM is unavailable.
    """
    result = CareerMatchResult(
        keyword_score=keyword_score,
        keyword_rec=keyword_rec,
    )

    api_key = _get_api_key()
    if not api_key:
        _fallback(result, resume)
        return result

    try:
        prompt = _USER_TEMPLATE.format(
            resume_text=resume.raw_text[:3500],
            vacancy_text=(vacancy.normalized_text or vacancy.raw_text)[:2000],
            keyword_score=keyword_score,
            keyword_rec=keyword_rec,
            archetype=resume.professional_archetype or "—",
            years=resume.years_experience,
            scale=resume.organizational_scale,
            domains=", ".join(resume.technology_domains[:6]) or "—",
            ai_count=len(resume.ai_signals),
            tf_count=len(resume.transformation_experience),
            framing_level=resume.executive_framing_level,
            framing_score=resume.executive_framing_score,
            strengths="; ".join(resume.strongest_assets[:3]) or "—",
            weak_vis="; ".join(resume.weak_visibility_areas[:2]) or "—",
        )

        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")].rstrip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        data = json.loads(raw)
        _apply(result, data)

    except Exception:
        _fallback(result, resume)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply(result: CareerMatchResult, data: dict[str, Any]) -> None:
    result.career_match_score        = int(data.get("career_match_score", 0))
    result.executive_summary         = data.get("executive_summary", "")
    result.trajectory_analysis       = data.get("trajectory_analysis", "")
    result.transferable_competencies = data.get("transferable_competencies") or []
    result.strategic_strengths       = data.get("strategic_strengths") or []
    result.risks_and_gaps            = data.get("risks_and_gaps") or []
    result.final_recommendation      = data.get("final_recommendation", "")
    result.recommendation_label      = data.get("recommendation_label", "УТОЧНИТЬ")


def _fallback(result: CareerMatchResult, resume: ResumeProfile) -> None:
    """Rule-based fallback when LLM unavailable."""
    result.career_match_score  = result.keyword_score
    result.executive_summary   = (
        f"Career match analysis требует подключения LLM. "
        f"Keyword score: {result.keyword_score}/100."
    )
    result.trajectory_analysis = "Анализ карьерной траектории недоступен без LLM."
    result.transferable_competencies = resume.strongest_assets[:3]
    result.strategic_strengths       = resume.technology_domains[:3]
    result.risks_and_gaps            = resume.weak_visibility_areas[:2]
    result.final_recommendation      = "Требуется LLM для полного career match анализа."
    result.recommendation_label      = result.keyword_rec or "УТОЧНИТЬ"
    result.confidence_notes.append("LLM недоступен — использован keyword score как career_match_score")


def _get_api_key() -> str:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key if key and not key.startswith("sk-ant-ВАШ") else ""
