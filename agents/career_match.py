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
from agents.resume_intelligence import ResumeProfile, format_roles_for_prompt


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
ВАКАНСИЯ:
---
{vacancy_text}
---

КАРЬЕРНАЯ ИСТОРИЯ КАНДИДАТА (структурированная):
---
{roles_history}
---

ПОЛНЫЙ ТЕКСТ РЕЗЮМЕ (используй если структурированная история неполная):
---
{raw_resume}
---

Дополнительный контекст:
- Keyword match score: {keyword_score}/100 · Rule-based: {keyword_rec}
- Архетип: {archetype} · Стаж: ~{years} лет · Масштаб: {scale}
- Домены: {domains} · AI signals: {ai_count} · Трансформация: {tf_count}
- Executive framing: {framing_level} ({framing_score}/100)

КРИТИЧЕСКИ ВАЖНО:
1. Анализируй ВСЕ позиции из карьерной истории, не только последнее место работы
2. В каждом пункте ОБЯЗАТЕЛЬНО ссылайся на конкретную компанию и период
   Формат: "В [Компания] ([период]) кандидат..."
   Пример: "В АО «ЛогистикПро» (2016–2020) управлял командой 65 человек..."
3. Ищи transferable компетенции в ранних позициях карьеры

Верни ТОЛЬКО валидный JSON (без markdown):
{{
  "career_match_score": 0-100,
  "executive_summary": "2-3 предложения: как ПОЛНАЯ карьера кандидата соответствует вакансии",
  "trajectory_analysis": "2-3 предложения: эволюция компетенций через ВСЕ компании и периоды",
  "transferable_competencies": [
    "В [Компания] ([период]) — конкретная компетенция → применимость к вакансии"
  ],
  "strategic_strengths": [
    "В [Компания] ([период]) — конкретная сила применительно к данной вакансии"
  ],
  "risks_and_gaps": [
    "конкретный риск или пробел с объяснением"
  ],
  "final_recommendation": "1-2 предложения итогового заключения как executive-рекрутер",
  "recommendation_label": "ОТКЛИКАТЬСЯ|УТОЧНИТЬ|ЗАПУСТИТЬ В РАБОТУ|ПРОПУСТИТЬ"
}}

career_match_score: 70+ прямое соответствие · 50-69 transferable fit · 30-49 требует валидации · <30 существенные риски
transferable_competencies: 4-6 пунктов с обязательной ссылкой на компанию/период
strategic_strengths: 4-5 с ссылкой на компанию/период
risks_and_gaps: 3-5 честных, конкретных"""


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
        roles_str = format_roles_for_prompt(resume.roles_history) if resume.roles_history else "— структурированные позиции не извлечены, используй полный текст ниже —"
        # Full resume text — no truncation. Sonnet has 200K context; a CV is ~10-20K chars max.
        raw_backup = resume.raw_text

        prompt = _USER_TEMPLATE.format(
            roles_history=roles_str,
            raw_resume=raw_backup,
            vacancy_text=(vacancy.normalized_text or vacancy.raw_text)[:4000],
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
        )

        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
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
