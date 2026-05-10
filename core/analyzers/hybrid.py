"""
HybridAnalyzer — rule-based scoring + LLM semantic insight placeholders.

Architecture for LLM integration:
  1. Subclass HybridAnalyzer and override _fill_llm_insights().
  2. Or replace HybridAnalyzer with a fully LLM-backed BaseAnalyzer subclass.
  3. Wire the new analyzer into core/analyzer.py::_analyzer.

The rule-based scoring layer (score, recommendation, key_matches, risks) is
intentionally kept separate from the semantic layer (role_level_fit, etc.)
so either part can evolve independently.
"""
from __future__ import annotations

from core.analyzers.base import BaseAnalyzer
from core.models import CandidateProfile, VacancyAnalysis

LLM_PENDING = "Ожидает подключения LLM"


class HybridAnalyzer(BaseAnalyzer):
    """
    Combines rule-based scoring with LLM semantic analysis.

    Currently fills LLM fields with a placeholder sentinel.
    When an LLM adapter is ready, override _fill_llm_insights() — the
    rule-based layer does not need to change.
    """

    def __init__(self, rule_based: BaseAnalyzer | None = None) -> None:
        if rule_based is None:
            from core.analyzers.rule_based import RuleBasedAnalyzer
            rule_based = RuleBasedAnalyzer()
        self._rule_based = rule_based

    def analyze(self, vacancy_text: str, profile: CandidateProfile) -> VacancyAnalysis:
        analysis = self._rule_based.analyze(vacancy_text, profile)
        self._fill_llm_insights(analysis, vacancy_text, profile)
        return analysis

    def _fill_llm_insights(
        self,
        analysis: VacancyAnalysis,
        vacancy_text: str,
        profile: CandidateProfile,
    ) -> None:
        """
        Populate LLM insight fields on the analysis object.

        Override this method in an LLM-backed subclass.
        Receives the completed rule-based analysis plus original inputs.
        Mutates analysis in-place; return value is ignored.
        """
        analysis.role_level_fit                   = LLM_PENDING
        analysis.strategic_vs_operational_balance = LLM_PENDING
        analysis.authority_signals                = []
        analysis.target_role_alignment            = LLM_PENDING
        analysis.semantic_summary                 = LLM_PENDING
