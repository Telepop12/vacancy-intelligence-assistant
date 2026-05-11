#!/usr/bin/env python3
"""Vacancy Intelligence Assistant — CLI entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Force UTF-8 on Windows terminals that default to cp1251
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import yaml

from core.analyzer import analyze
from core.models import CandidateProfile, ScoringGroup
from core.report import save_json, save_markdown, update_registry

ROOT = Path(__file__).parent
DEFAULT_PROFILE = ROOT / "config" / "candidate_profile.yaml"
DEFAULT_OUTPUT = ROOT / "output"
REGISTRY_FILE = DEFAULT_OUTPUT / "registry.csv"

_REC_ICONS = {
    "ОТКЛИКАТЬСЯ":        "✅",
    "УТОЧНИТЬ":           "⚠️ ",
    "ЗАПУСТИТЬ В РАБОТУ": "🚀",
    "ПРОПУСТИТЬ":         "🚫",
}


def load_profile(path: Path) -> CandidateProfile:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    scoring_groups = {
        name: ScoringGroup(weight=g["weight"], keywords=g.get("keywords", []))
        for name, g in data.get("scoring_groups", {}).items()
    }
    red_flags = dict(data.get("red_flags", {}))
    return CandidateProfile(
        name=data["name"],
        target_roles=data.get("target_roles", []),
        scoring_groups=scoring_groups,
        red_flags=red_flags,
        seniority_keywords=data.get("seniority_keywords", []),
    )


def read_vacancy_interactive() -> str:
    print("Введите текст вакансии. Для завершения введите строку с одним символом «.»:")
    print()
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    return "\n".join(lines)


def print_summary(analysis) -> None:
    sep = "─" * 55
    # Prefer LLM-enhanced recommended_action when available
    display = analysis.recommended_action or analysis.recommendation.value
    icon = _REC_ICONS.get(display, "")
    print(f"\n{sep}")
    print(f"  Match Score  : {analysis.match_score} / 100")
    print(f"  Рекомендация : {icon} {display}")
    if display != analysis.recommendation.value:
        print(f"  Rule-based   : {analysis.recommendation.value}")
    if analysis.evolutionary_potential and analysis.evolutionary_potential not in ("", "Ожидает подключения LLM"):
        print(f"  Эво.потенциал: {analysis.evolutionary_potential}")
    print(f"{sep}")
    if analysis.key_matches:
        top = ", ".join(analysis.key_matches[:6])
        print(f"  Совпадения   : {top}")
    if analysis.risks:
        print("  Риски        :")
        for r in analysis.risks:
            print(f"    • {r}")
    print(f"{sep}\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vacancy-ai",
        description="Vacancy Intelligence Assistant — анализ вакансий для CIO/CTO/CDTO",
    )
    p.add_argument(
        "--file", "-f",
        type=Path,
        metavar="PATH",
        help="Путь к .txt файлу с текстом вакансии",
    )
    p.add_argument(
        "--profile", "-p",
        type=Path,
        default=DEFAULT_PROFILE,
        metavar="YAML",
        help=f"Профиль кандидата (по умолчанию: {DEFAULT_PROFILE})",
    )
    p.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        metavar="DIR",
        help=f"Директория для отчётов (по умолчанию: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--no-registry",
        action="store_true",
        help="Не обновлять реестр вакансий (registry.csv)",
    )
    return p


def main() -> None:
    args = build_parser().parse_args()

    # --- resolve vacancy text ---
    source_file: str | None = None
    if args.file:
        if not args.file.exists():
            print(f"Ошибка: файл не найден — {args.file}", file=sys.stderr)
            sys.exit(1)
        vacancy_text = args.file.read_text(encoding="utf-8")
        source_file = str(args.file)
    elif not sys.stdin.isatty():
        vacancy_text = sys.stdin.read()
        source_file = "stdin"
    else:
        vacancy_text = read_vacancy_interactive()

    if not vacancy_text.strip():
        print("Ошибка: текст вакансии пуст.", file=sys.stderr)
        sys.exit(1)

    # --- load profile ---
    if not args.profile.exists():
        print(f"Ошибка: профиль не найден — {args.profile}", file=sys.stderr)
        sys.exit(1)
    profile = load_profile(args.profile)

    # --- analyze ---
    print(f"Анализирую вакансию (профиль: {profile.name})…")
    analysis = analyze(vacancy_text, profile)
    analysis.source_file = source_file

    # --- save reports ---
    args.output.mkdir(parents=True, exist_ok=True)
    md_path = save_markdown(analysis, args.output)
    json_path = save_json(analysis, args.output)

    registry_path = args.output / "registry.csv"
    if not args.no_registry:
        update_registry(analysis, registry_path)

    # --- print summary ---
    print_summary(analysis)
    print("Отчёты сохранены:")
    print(f"  Markdown : {md_path}")
    print(f"  JSON     : {json_path}")
    if not args.no_registry:
        print(f"  Реестр   : {registry_path}")


if __name__ == "__main__":
    main()
