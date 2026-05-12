"""
Public analyze() entry point — backward-compatible.

Auto-detects ANTHROPIC_API_KEY (from environment or .env file) and uses
ClaudeAnalyzer when available; falls back to HybridAnalyzer (placeholder
LLM fields) when the key is absent or invalid.
"""
from __future__ import annotations

import os
from pathlib import Path

from core.models import CandidateProfile, VacancyAnalysis

# ---------------------------------------------------------------------------
# Load .env (if present) before checking for the API key
# ---------------------------------------------------------------------------

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


# ---------------------------------------------------------------------------
# Build analyzer — ClaudeAnalyzer if API key present, else HybridAnalyzer
# ---------------------------------------------------------------------------

def _build_analyzer():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key and not api_key.startswith("sk-ant-ВАШ"):
        from core.analyzers.claude_analyzer import ClaudeAnalyzer
        return ClaudeAnalyzer(api_key=api_key)
    from core.analyzers.hybrid import HybridAnalyzer
    return HybridAnalyzer()


_analyzer = _build_analyzer()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(vacancy, profile: CandidateProfile) -> VacancyAnalysis:
    """
    Analyze a vacancy against the candidate profile.

    Accepts either a VacancyInput (preferred) or a raw str (backward-compat).
    Raw strings are automatically wrapped via the intake pipeline.
    """
    from agents.intake import VacancyInput, from_text
    from core.recommendation_engine import synthesize

    if isinstance(vacancy, str):
        vacancy = from_text(vacancy)

    analysis = _analyzer.analyze(vacancy.normalized_text or vacancy.raw_text, profile)
    synthesize(analysis)

    # Populate intake fields on the analysis result
    analysis.intake_source_type     = vacancy.source_type.value
    analysis.intake_source_name     = vacancy.source_name
    analysis.intake_confidence      = vacancy.intake_confidence.value
    analysis.intake_confidence_notes = vacancy.confidence_notes
    analysis.intake_detected_title   = vacancy.title
    analysis.intake_detected_company = vacancy.company
    analysis.intake_detected_location = vacancy.location
    analysis.intake_detected_salary  = vacancy.salary
    analysis.intake_url              = vacancy.url

    # Keep source_file in sync for backward compat
    if not analysis.source_file:
        analysis.source_file = vacancy.source_name

    return analysis


# Re-exported for backward compatibility
from core.scoring import THRESHOLD_APPLY  # noqa: E402
