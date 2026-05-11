"""
Decision Intelligence Layer — synthesizes executive-level recommendation.

Combines:
  - deterministic keyword scoring (match_score, recommendation)
  - semantic LLM analysis (role_level_fit, semantic_summary)
  - evolutionary potential (evolutionary_potential, strategic_opportunity_signals)
  - authority signals
  - career trajectory reasoning

Works in two modes:
  1. LLM-connected: validates Claude output, fills any remaining gaps
  2. Rule-based fallback: generates deterministic content from scoring data

synthesize() is always called after the analyzer chain. It is idempotent:
fields already populated by Claude are never overwritten.
"""
from __future__ import annotations

from core.models import Recommendation, VacancyAnalysis

_LLM_PENDING = "Ожидает подключения LLM"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def synthesize(analysis: VacancyAnalysis) -> None:
    """
    Post-process VacancyAnalysis: synthesize final recommended_action,
    generate rationale, risks, opportunities, scenarios, and validation
    questions. Mutates analysis in-place; safe to call with or without LLM.
    """
    _ensure_recommended_action(analysis)
    _fill_rationale_if_missing(analysis)
    _fill_career_risks_if_missing(analysis)
    _fill_career_opportunities_if_missing(analysis)
    _fill_scenarios_if_missing(analysis)
    _fill_validation_questions_if_missing(analysis)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _missing(value) -> bool:
    """True when a field is absent, empty, or an LLM placeholder."""
    if not value:
        return True
    if isinstance(value, str) and (value == _LLM_PENDING or not value.strip()):
        return True
    return False


def _action(analysis: VacancyAnalysis) -> str:
    return analysis.recommended_action or analysis.recommendation.value


# ---------------------------------------------------------------------------
# Synthesis steps
# ---------------------------------------------------------------------------

def _ensure_recommended_action(analysis: VacancyAnalysis) -> None:
    """
    Synthesize recommended_action from all signals.

    Synthesis rule always takes precedence over the default rule-based mirror:
      - evo High + score < 70  → ЗАПУСТИТЬ В РАБОТУ
      - score >= 70            → ОТКЛИКАТЬСЯ
      - score 45–69            → УТОЧНИТЬ
      - score < 45, evo not High → ПРОПУСТИТЬ

    LLM output (non-placeholder, non-default) is trusted AFTER applying
    the evo-High synthesis rule.  This prevents Claude's deliberate choice
    from being silently overridden, while still letting the synthesis engine
    upgrade a ПРОПУСТИТЬ when evo signals clearly justify it.
    """
    score = analysis.match_score
    evo = analysis.evolutionary_potential
    current = analysis.recommended_action

    # Primary synthesis rule: evo High always upgrades low-score to LAUNCH
    if evo == "High" and score < 70:
        analysis.recommended_action = Recommendation.LAUNCH.value
        return

    # Trust explicit LLM output (non-empty, non-placeholder)
    if current and current not in (_LLM_PENDING,):
        return

    # Fallback: derive from score alone
    if score >= 70:
        analysis.recommended_action = Recommendation.APPLY.value
    elif score >= 45:
        analysis.recommended_action = Recommendation.CLARIFY.value
    else:
        analysis.recommended_action = Recommendation.SKIP.value


def _fill_rationale_if_missing(analysis: VacancyAnalysis) -> None:
    if not _missing(analysis.strategic_rationale):
        return

    act = _action(analysis)
    score = analysis.match_score
    matches = analysis.key_matches[:4]

    if act == Recommendation.APPLY.value:
        match_str = ", ".join(matches) if matches else "не определены"
        analysis.strategic_rationale = (
            f"Вакансия демонстрирует высокое соответствие профилю (score {score}/100). "
            f"Ключевые совпадения: {match_str}. "
            "Рекомендуется отклик — прямое совпадение с целевой ролью CIO/CTO/CDTO."
        )
    elif act == Recommendation.LAUNCH.value:
        analysis.strategic_rationale = (
            f"Несмотря на умеренный формальный match score ({score}/100), "
            "роль обладает высоким стратегическим потенциалом и сигналами эволюции карьеры. "
            "Может стать точкой входа в AI leadership trajectory (Head of AI → CDTO)."
        )
    elif act == Recommendation.CLARIFY.value:
        analysis.strategic_rationale = (
            f"Частичное соответствие профилю (score {score}/100). "
            "Необходимо уточнить реальные полномочия, бюджетную ответственность "
            "и возможности развития роли до стратегического уровня."
        )
    else:
        analysis.strategic_rationale = (
            f"Низкое соответствие профилю CIO/CTO/CDTO (score {score}/100). "
            "Отсутствуют значимые сигналы стратегической ценности для AI leadership trajectory. "
            "Инвестиция времени нецелесообразна."
        )


def _fill_career_risks_if_missing(analysis: VacancyAnalysis) -> None:
    if not _missing(analysis.career_risks):
        return

    risks: list[str] = []
    act = _action(analysis)
    score = analysis.match_score

    if analysis.risks:
        risks.extend(analysis.risks[:3])

    if score < 45 and act != Recommendation.LAUNCH.value:
        risks.append("Низкий формальный fit — высок риск несоответствия ожиданий работодателя")

    if act == Recommendation.LAUNCH.value:
        risks.extend([
            "Operational trap — роль может остаться уровня PM без эволюции к стратегии",
            "Отсутствие структурного authority (P&L, команда) ограничивает C-level траекторию",
            "Зависимость от личного sponsor: смена руководства = потеря контекста роли",
        ])
    elif act == Recommendation.CLARIFY.value:
        risks.append("Смешанные сигналы: роль может оказаться операционной без пути к C-level")
    elif act == Recommendation.SKIP.value:
        risks.append("Ограниченный потенциал роста к стратегическому уровню")

    analysis.career_risks = risks if risks else ["Недостаточно данных для детальной оценки карьерных рисков"]


def _fill_career_opportunities_if_missing(analysis: VacancyAnalysis) -> None:
    if not _missing(analysis.career_opportunities):
        return

    opportunities: list[str] = []
    act = _action(analysis)

    if analysis.strategic_opportunity_signals:
        opportunities.extend(analysis.strategic_opportunity_signals[:3])

    if analysis.evolutionary_potential == "High":
        opportunities.append("Высокий эволюционный потенциал для AI leadership trajectory")

    if analysis.key_matches:
        top = ", ".join(analysis.key_matches[:3])
        opportunities.append(f"Подтверждённое совпадение компетенций: {top}")

    if act == Recommendation.APPLY.value:
        opportunities.append("Прямое соответствие целевой роли — высокий шанс успешного отклика")

    analysis.career_opportunities = (
        opportunities if opportunities
        else ["Недостаточно данных для детальной оценки карьерных возможностей"]
    )


def _fill_scenarios_if_missing(analysis: VacancyAnalysis) -> None:
    act = _action(analysis)

    if _missing(analysis.best_case_scenario):
        if act == Recommendation.APPLY.value:
            analysis.best_case_scenario = (
                "Прямой вход на C-level позицию с реальными полномочиями: "
                "формирование стратегии, команды и AI-roadmap компании"
            )
        elif act == Recommendation.LAUNCH.value:
            analysis.best_case_scenario = (
                "AI Lead → Head of AI Transformation → CDTO: "
                "успешная реализация AI-программы открывает стратегическую позицию"
            )
        elif act == Recommendation.CLARIFY.value:
            analysis.best_case_scenario = (
                "После уточнений роль раскрывается как стратегическая с реальным P&L, "
                "командой и доступом к decision-making на уровне board"
            )
        else:
            analysis.best_case_scenario = (
                "Ограниченное применение экспертизы в узком контексте "
                "без существенного карьерного продвижения"
            )

    if _missing(analysis.worst_case_scenario):
        if act == Recommendation.APPLY.value:
            analysis.worst_case_scenario = (
                "Высокие ожидания при недостаточных полномочиях: "
                "формальный C-level без реального влияния на стратегию"
            )
        elif act == Recommendation.LAUNCH.value:
            analysis.worst_case_scenario = (
                "Долгосрочная операционная роль AI PM без эволюции к стратегии: "
                "потеря 2–3 лет без движения к CDTO/CIO траектории"
            )
        elif act == Recommendation.CLARIFY.value:
            analysis.worst_case_scenario = (
                "Роль оказывается операционной delivery-позицией "
                "без пути к C-level и стратегическим полномочиям"
            )
        else:
            analysis.worst_case_scenario = (
                "Карьерная стагнация: время и ресурсы вложены в роль "
                "без стратегической ценности для AI leadership"
            )


def _fill_validation_questions_if_missing(analysis: VacancyAnalysis) -> None:
    if not _missing(analysis.strategic_validation_questions):
        return

    act = _action(analysis)

    if act == Recommendation.LAUNCH.value:
        questions = [
            "Кто является executive sponsor AI-инициативы — CEO или board?",
            "Планируется ли создание AI Office или выделенного AI-подразделения?",
            "Будет ли расширяться scope роли после первых measurable результатов?",
            "Предусмотрен ли явный growth path к Head of AI / CDTO?",
            "Кто владеет AI strategy на уровне совета директоров?",
        ]
    elif act == Recommendation.CLARIFY.value:
        questions = [
            "Каков реальный уровень стратегической ответственности (P&L, бюджет компании)?",
            "Есть ли прямой доступ к CEO / совету директоров для защиты инициатив?",
            "Предполагается ли участие в определении стратегии, а не только в её исполнении?",
            "Каковы планы компании по AI/цифровой трансформации в ближайшие 2–3 года?",
            "Какова структура подчинения и кто является линейным руководителем?",
        ]
    elif act == Recommendation.APPLY.value:
        questions = [
            "Каков реальный бюджет направления и уровень CAPEX/OPEX-полномочий?",
            "Как выглядит ИТ-стратегия компании на 3–5 лет и кто её формирует?",
            "Каков текущий уровень AI-зрелости и приоритеты трансформации?",
            "Предусмотрена ли возможность формировать команду с нуля или это rebuild?",
        ]
    else:
        questions = [
            "Есть ли стратегические проекты уровня CEO, в которых можно участвовать?",
            "Каков горизонт трансформации роли до уровня стратегического лидера?",
            "Кто принимает решения об AI-инвестициях в компании?",
        ]

    analysis.strategic_validation_questions = questions
