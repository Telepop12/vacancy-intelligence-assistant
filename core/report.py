from __future__ import annotations

import csv
import json
from pathlib import Path

from core.models import VacancyAnalysis


def _bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- —"


def _llm_sections(analysis: VacancyAnalysis) -> list[str]:
    """Return Markdown lines for LLM insight fields, or [] if none populated."""
    lines: list[str] = []

    # Evolutionary Potential block
    evo_fields = [
        analysis.evolutionary_potential,
        analysis.career_strategy_comment,
        analysis.strategic_opportunity_signals,
        analysis.recommended_action,
    ]
    if any(evo_fields):
        lines += ["", "## Эволюционный потенциал", ""]
        if analysis.evolutionary_potential:
            lines.append(f"**Потенциал:** {analysis.evolutionary_potential}")
        if analysis.recommended_action:
            lines.append(f"**Рекомендованное действие:** {analysis.recommended_action}")
        if analysis.career_strategy_comment:
            lines += ["", analysis.career_strategy_comment]
        if analysis.strategic_opportunity_signals:
            lines += ["", "**Сигналы возможности:**"]
            lines += [f"- {s}" for s in analysis.strategic_opportunity_signals]

    # Semantic insights block
    sem_fields = [
        ("Семантическое резюме",          analysis.semantic_summary),
        ("Соответствие уровню роли",       analysis.role_level_fit),
        ("Баланс стратегия / операционка", analysis.strategic_vs_operational_balance),
        ("Соответствие целевой роли",       analysis.target_role_alignment),
    ]
    if any(v for _, v in sem_fields) or analysis.authority_signals:
        lines += ["", "## LLM-инсайты", ""]
        for label, value in sem_fields:
            if value:
                lines.append(f"**{label}:** {value}")
        if analysis.authority_signals:
            lines.append(f"**Сигналы полномочий:** {'; '.join(analysis.authority_signals)}")

    return lines


def save_markdown(analysis: VacancyAnalysis, output_dir: Path) -> Path:
    ts = analysis.analyzed_at.strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"analysis_{ts}.md"

    sections = [
        f"# Анализ вакансии — {analysis.analyzed_at.strftime('%d.%m.%Y %H:%M')}",
        "",
        f"**Match Score:** {analysis.match_score} / 100",
        f"**Рекомендация:** {analysis.recommendation.value}",
        f"**Источник:** {analysis.source_file or 'консольный ввод'}",
        "",
        "---",
        "",
        "## Ключевые совпадения с профилем",
        _bullet_list(analysis.key_matches),
        "",
        "## Риски и красные флаги",
        _bullet_list(analysis.risks) if analysis.risks else "- Существенных рисков не выявлено",
        "",
        "## Вопросы к HR",
        _bullet_list(analysis.hr_questions),
        "",
        "## Шаблон ответа HR",
        "```",
        analysis.hr_response,
        "```",
        "",
        "## Рекомендации по адаптации резюме",
        _bullet_list(analysis.resume_tips),
        *_llm_sections(analysis),
    ]

    path.write_text("\n".join(sections), encoding="utf-8")
    return path


def save_json(analysis: VacancyAnalysis, output_dir: Path) -> Path:
    ts = analysis.analyzed_at.strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"analysis_{ts}.json"

    payload = {
        "analyzed_at": analysis.analyzed_at.isoformat(),
        "source_file": analysis.source_file,
        "match_score": analysis.match_score,
        "recommendation": analysis.recommendation.value,
        "key_matches": analysis.key_matches,
        "risks": analysis.risks,
        "hr_questions": analysis.hr_questions,
        "hr_response": analysis.hr_response,
        "resume_tips": analysis.resume_tips,
        "llm_insights": {
            "semantic_summary":                  analysis.semantic_summary,
            "role_level_fit":                    analysis.role_level_fit,
            "strategic_vs_operational_balance":  analysis.strategic_vs_operational_balance,
            "authority_signals":                 analysis.authority_signals,
            "target_role_alignment":             analysis.target_role_alignment,
        },
        "evolutionary_potential": {
            "level":                             analysis.evolutionary_potential,
            "strategic_opportunity_signals":     analysis.strategic_opportunity_signals,
            "career_strategy_comment":           analysis.career_strategy_comment,
            "recommended_action":                analysis.recommended_action,
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def update_registry(analysis: VacancyAnalysis, registry_path: Path) -> None:
    write_header = not registry_path.exists()
    with registry_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if write_header:
            writer.writerow(["date", "score", "recommendation", "source", "top_matches"])
        writer.writerow([
            analysis.analyzed_at.strftime("%Y-%m-%d %H:%M"),
            analysis.match_score,
            analysis.recommendation.value,
            analysis.source_file or "stdin",
            "; ".join(analysis.key_matches[:5]),
        ])
