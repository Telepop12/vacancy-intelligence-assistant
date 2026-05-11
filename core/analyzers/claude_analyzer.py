"""
ClaudeAnalyzer — HybridAnalyzer backed by Claude API.

Fills both semantic insight fields and Evolutionary Potential layer.
Falls back to placeholder text on any error so the rest of the analysis is never lost.
"""
from __future__ import annotations

import json
from typing import Any

from core.analyzers.hybrid import HybridAnalyzer, LLM_PENDING
from core.models import CandidateProfile, VacancyAnalysis

_SYSTEM_PROMPT = """\
Ты — стратегический эксперт по карьере топ-менеджмента уровня CIO/CTO/CDTO/CAIO.
Анализируешь вакансии для опытного ИТ-руководителя с перспективой AI leadership.
Отвечай строго в формате JSON без лишнего текста. Все текстовые значения — на русском языке."""

_USER_TEMPLATE = """\
Вакансия:
---
{vacancy_text}
---

Контекст rule-based анализа:
- Match Score: {score}/100  (ОТКЛИКАТЬСЯ ≥70 / УТОЧНИТЬ 45–69 / ПРОПУСТИТЬ <45)
- Rule-based рекомендация: {recommendation}
- Ключевые совпадения: {matches}

Верни ТОЛЬКО валидный JSON (без markdown-обёртки, без пояснений):
{{
  "semantic_summary": "2-3 предложения о сути роли и её соответствии профилю CIO/CDTO",
  "role_level_fit": "C-level позиция или нет? Конкретное обоснование.",
  "strategic_vs_operational_balance": "Примерный баланс стратегической / операционной работы.",
  "authority_signals": ["конкретный сигнал полномочий из текста"],
  "target_role_alignment": "Соответствие целевым ролям CIO/CTO/CDTO кандидата.",
  "evolutionary_potential": "High|Medium|Low",
  "strategic_opportunity_signals": ["конкретный сигнал потенциала из текста"],
  "career_strategy_comment": "Почему роль стратегически интересна или нет. 2-3 предложения.",
  "recommended_action": "ОТКЛИКАТЬСЯ|УТОЧНИТЬ|ЗАПУСТИТЬ В РАБОТУ|ПРОПУСТИТЬ"
}}

Логика evolutionary_potential:
- High: 3+ сигнала: прямой доступ к CEO/board, ownership AI с нуля, measurable ROI, кросс-функц. влияние, ранняя стадия AI в крупной организации
- Medium: 1-2 сигнала
- Low: нет значимых сигналов

Логика recommended_action:
- ОТКЛИКАТЬСЯ: rule-based ≥70 — не понижай без веской причины
- ЗАПУСТИТЬ В РАБОТУ: rule-based УТОЧНИТЬ/ПРОПУСТИТЬ, НО evolutionary_potential=High
- УТОЧНИТЬ: rule-based УТОЧНИТЬ и evo не High
- ПРОПУСТИТЬ: rule-based ПРОПУСТИТЬ и нет evo потенциала"""


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
        # Set all placeholders first — guarantees non-empty fields on any error
        super()._fill_llm_insights(analysis, vacancy_text, profile)
        try:
            data = self._call_claude(analysis, vacancy_text)

            # Semantic layer
            analysis.semantic_summary                 = data.get("semantic_summary") or LLM_PENDING
            analysis.role_level_fit                   = data.get("role_level_fit") or LLM_PENDING
            analysis.strategic_vs_operational_balance = data.get("strategic_vs_operational_balance") or LLM_PENDING
            analysis.authority_signals                = data.get("authority_signals") or []
            analysis.target_role_alignment            = data.get("target_role_alignment") or LLM_PENDING

            # Evolutionary Potential layer
            analysis.evolutionary_potential           = data.get("evolutionary_potential") or LLM_PENDING
            analysis.strategic_opportunity_signals    = data.get("strategic_opportunity_signals") or []
            analysis.career_strategy_comment          = data.get("career_strategy_comment") or LLM_PENDING
            analysis.recommended_action               = data.get("recommended_action") or analysis.recommendation.value

        except Exception:
            pass  # placeholders already set; analysis remains fully usable

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
            max_tokens=2000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code-block wrapper if Claude added one
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")].rstrip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        return json.loads(raw)
