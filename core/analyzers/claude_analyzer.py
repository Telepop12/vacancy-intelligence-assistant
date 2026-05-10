"""
ClaudeAnalyzer — HybridAnalyzer backed by Claude API.

Calls Claude to fill LLM insight fields. Falls back to placeholder
text on any error so the rest of the analysis is never lost.
"""
from __future__ import annotations

import json
from typing import Any

from core.analyzers.hybrid import HybridAnalyzer, LLM_PENDING
from core.models import CandidateProfile, VacancyAnalysis

_SYSTEM_PROMPT = """\
Ты — эксперт по найму топ-менеджмента уровня CIO/CTO/CDTO.
Анализируешь вакансии для опытного ИТ-руководителя.
Отвечай строго в формате JSON без лишнего текста.
Все текстовые значения — на русском языке."""

_USER_TEMPLATE = """\
Вакансия:
---
{vacancy_text}
---

Контекст rule-based анализа:
- Match Score: {score}/100
- Рекомендация: {recommendation}
- Ключевые совпадения: {matches}

Верни JSON с этими полями (все значения на русском):
{{
  "semantic_summary": "2-3 предложения: суть роли и почему она подходит или не подходит для CIO-кандидата",
  "role_level_fit": "Это действительно C-level/директорская позиция или что-то другое? Конкретное обоснование.",
  "strategic_vs_operational_balance": "Примерный баланс стратегической и операционной работы с объяснением.",
  "authority_signals": ["конкретный сигнал из текста", "ещё один сигнал"],
  "target_role_alignment": "Насколько позиция соответствует целевым ролям CIO/CTO/CDTO кандидата."
}}"""


class ClaudeAnalyzer(HybridAnalyzer):
    """HybridAnalyzer that replaces placeholder fields with real Claude insights."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model

    def _fill_llm_insights(
        self,
        analysis: VacancyAnalysis,
        vacancy_text: str,
        profile: CandidateProfile,
    ) -> None:
        # Set placeholders first — guarantees non-empty fields on any error
        super()._fill_llm_insights(analysis, vacancy_text, profile)
        try:
            data = self._call_claude(analysis, vacancy_text)
            analysis.semantic_summary                 = data.get("semantic_summary") or LLM_PENDING
            analysis.role_level_fit                   = data.get("role_level_fit") or LLM_PENDING
            analysis.strategic_vs_operational_balance = data.get("strategic_vs_operational_balance") or LLM_PENDING
            analysis.authority_signals                = data.get("authority_signals") or []
            analysis.target_role_alignment            = data.get("target_role_alignment") or LLM_PENDING
        except Exception:
            pass  # placeholders already set; analysis remains usable

    def _call_claude(self, analysis: VacancyAnalysis, vacancy_text: str) -> dict[str, Any]:
        import anthropic

        prompt = _USER_TEMPLATE.format(
            vacancy_text=vacancy_text[:3000],
            score=analysis.match_score,
            recommendation=analysis.recommendation.value,
            matches=", ".join(analysis.key_matches[:8]) or "—",
        )

        client = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Extract JSON even if Claude wrapped it in markdown fences
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        return json.loads(raw)
