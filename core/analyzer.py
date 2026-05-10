"""
Public analyze() entry point — backward-compatible.

Delegates to HybridAnalyzer (RuleBasedAnalyzer + LLM placeholders).

To swap the underlying analyzer at runtime:
    from core import analyzer as core_analyzer
    from core.analyzers.rule_based import RuleBasedAnalyzer
    core_analyzer._analyzer = RuleBasedAnalyzer()

To connect an LLM backend:
    from core.analyzers.hybrid import HybridAnalyzer
    class ClaudeAnalyzer(HybridAnalyzer):
        def _fill_llm_insights(self, analysis, vacancy_text, profile):
            ...  # call Claude API here
    core_analyzer._analyzer = ClaudeAnalyzer()
"""
from __future__ import annotations

from core.analyzers.hybrid import HybridAnalyzer
from core.models import CandidateProfile, VacancyAnalysis

_analyzer: HybridAnalyzer = HybridAnalyzer()


def analyze(vacancy_text: str, profile: CandidateProfile) -> VacancyAnalysis:
    """
    Analyze a vacancy against the candidate profile.
    Signature is stable — safe to call from CLI, Web UI, or tests.
    """
    return _analyzer.analyze(vacancy_text, profile)


# Re-exported for backward compatibility (some modules import THRESHOLD_APPLY from here)
from core.scoring import THRESHOLD_APPLY  # noqa: E402
