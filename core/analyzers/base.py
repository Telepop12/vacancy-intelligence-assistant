from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import CandidateProfile, VacancyAnalysis


class BaseAnalyzer(ABC):
    """
    Abstract base for vacancy analyzers.

    To plug in a new backend (LLM, hybrid, mock):
    1. Subclass BaseAnalyzer.
    2. Implement analyze().
    3. Wire it in core/analyzer.py or pass it to HybridAnalyzer.
    """

    @abstractmethod
    def analyze(self, vacancy_text: str, profile: CandidateProfile) -> VacancyAnalysis:
        ...
