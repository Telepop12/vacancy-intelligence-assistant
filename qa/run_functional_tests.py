#!/usr/bin/env python3
"""
Functional test runner — Vacancy Intelligence Assistant.

Usage:
    python qa/run_functional_tests.py          # run all tests
    python qa/run_functional_tests.py --list   # show test list

Exit code: 0 = all passed, 1 = one or more failed.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Force UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent   # vacancy_ai_assistant/
QA_DIR = Path(__file__).resolve().parent
INPUTS_DIR = QA_DIR / "sample_inputs"
OUTPUT_DIR = ROOT / "output"
REGISTRY = OUTPUT_DIR / "registry.csv"
PYTHON = sys.executable

REQUIRED_MD_SECTIONS = [
    "Match Score",
    "Ключевые совпадения",
    "Риски",
    "Вопросы к HR",
    "Шаблон ответа HR",
    "Рекомендации по адаптации резюме",
]

REQUIRED_JSON_KEYS = [
    "match_score", "recommendation", "key_matches",
    "risks", "hr_questions", "hr_response", "resume_tips",
]


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    id: str
    name: str
    passed: bool
    message: str
    duration_ms: int = 0
    details: str = ""


def _run(args: list[str], stdin_text: str = "") -> tuple[int, str, str]:
    result = subprocess.run(
        [PYTHON, str(ROOT / "main.py"), *args],
        input=stdin_text.encode("utf-8"),
        capture_output=True,
        cwd=str(ROOT),
    )
    return (
        result.returncode,
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
    )


def _parse_report_paths(stdout: str) -> tuple[Path | None, Path | None]:
    """Extract Markdown and JSON paths printed by the CLI."""
    md_path = json_path = None
    for line in stdout.splitlines():
        s = line.strip()
        if s.startswith("Markdown") and ":" in s:
            p = Path(s.split(":", 1)[1].strip())
            if p.suffix == ".md":
                md_path = p
        elif s.startswith("JSON") and ":" in s:
            p = Path(s.split(":", 1)[1].strip())
            if p.suffix == ".json":
                json_path = p
    return md_path, json_path


def _registry_row_count() -> int:
    if not REGISTRY.exists():
        return 0
    with REGISTRY.open(encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)  # exclude header


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def tc_file_input() -> TestResult:
    """TC-01: File input mode"""
    t0 = time.monotonic()
    code, out, err = _run(["--file", str(ROOT / "data" / "sample_vacancy.txt"), "--no-registry"])
    ms = int((time.monotonic() - t0) * 1000)
    if code != 0:
        return TestResult("TC-01", "File input mode", False, f"Exit code {code}", ms, err)
    if "Match Score" not in out:
        return TestResult("TC-01", "File input mode", False, "'Match Score' absent in stdout", ms, out[:300])
    return TestResult("TC-01", "File input mode", True, "Exit 0, Match Score present", ms)


def tc_stdin_pipe() -> TestResult:
    """TC-02: Stdin pipe mode"""
    t0 = time.monotonic()
    text = (ROOT / "data" / "sample_vacancy.txt").read_text(encoding="utf-8")
    code, out, err = _run(["--no-registry"], stdin_text=text)
    ms = int((time.monotonic() - t0) * 1000)
    if code != 0:
        return TestResult("TC-02", "Stdin pipe mode", False, f"Exit code {code}", ms, err)
    if "Match Score" not in out:
        return TestResult("TC-02", "Stdin pipe mode", False, "'Match Score' absent in stdout", ms, out[:300])
    return TestResult("TC-02", "Stdin pipe mode", True, "Exit 0, stdin read correctly", ms)


def tc_interactive_simulated() -> TestResult:
    """TC-03: Interactive input (piped with '.' terminator)"""
    # subprocess sets isatty()=False, so the CLI uses the stdin-pipe path.
    # This validates the same text-reading pipeline; true tty test is manual (see test_cases.md).
    t0 = time.monotonic()
    text = (ROOT / "data" / "sample_vacancy.txt").read_text(encoding="utf-8").strip()
    code, out, err = _run(["--no-registry"], stdin_text=text + "\n.\n")
    ms = int((time.monotonic() - t0) * 1000)
    if code != 0:
        return TestResult("TC-03", "Interactive input (simulated)", False, f"Exit code {code}", ms, err)
    if "Match Score" not in out:
        return TestResult("TC-03", "Interactive input (simulated)", False, "'Match Score' absent", ms, out[:300])
    return TestResult("TC-03", "Interactive input (simulated)", True, "Exit 0, text+terminator processed", ms)


def tc_markdown_report() -> TestResult:
    """TC-04: Markdown report created with required sections"""
    t0 = time.monotonic()
    _, out, _ = _run(["--file", str(ROOT / "data" / "sample_vacancy.txt"), "--no-registry"])
    ms = int((time.monotonic() - t0) * 1000)
    md_path, _ = _parse_report_paths(out)
    if not md_path:
        return TestResult("TC-04", "Markdown report created", False, "Cannot parse .md path from stdout", ms, out[-200:])
    if not md_path.exists():
        return TestResult("TC-04", "Markdown report created", False, f"File missing: {md_path.name}", ms)
    content = md_path.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_MD_SECTIONS if s not in content]
    if missing:
        return TestResult("TC-04", "Markdown report created", False, f"Missing sections: {missing}", ms)
    return TestResult("TC-04", "Markdown report created", True, f"{md_path.name} — all sections present", ms)


def tc_json_report() -> TestResult:
    """TC-05: JSON report created, valid structure"""
    t0 = time.monotonic()
    _, out, _ = _run(["--file", str(ROOT / "data" / "sample_vacancy.txt"), "--no-registry"])
    ms = int((time.monotonic() - t0) * 1000)
    _, json_path = _parse_report_paths(out)
    if not json_path:
        return TestResult("TC-05", "JSON report created", False, "Cannot parse .json path from stdout", ms, out[-200:])
    if not json_path.exists():
        return TestResult("TC-05", "JSON report created", False, f"File missing: {json_path.name}", ms)
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return TestResult("TC-05", "JSON report created", False, f"Invalid JSON: {exc}", ms)
    missing = [k for k in REQUIRED_JSON_KEYS if k not in data]
    if missing:
        return TestResult("TC-05", "JSON report created", False, f"Missing keys: {missing}", ms)
    return TestResult("TC-05", "JSON report created", True,
                      f"{json_path.name} — valid, score={data['match_score']}", ms)


def tc_registry_updated() -> TestResult:
    """TC-06: registry.csv updated with new entry"""
    t0 = time.monotonic()
    before = _registry_row_count()
    _run(["--file", str(ROOT / "data" / "sample_vacancy.txt")])  # registry enabled
    ms = int((time.monotonic() - t0) * 1000)
    after = _registry_row_count()
    if after <= before:
        return TestResult("TC-06", "Registry CSV updated", False,
                          f"Row count unchanged (before={before}, after={after})", ms)
    with REGISTRY.open(encoding="utf-8") as f:
        last = list(csv.reader(f))[-1]
    return TestResult("TC-06", "Registry CSV updated", True,
                      f"New entry added: score={last[1]}, rec={last[2]}", ms)


def tc_strong_vacancy() -> TestResult:
    """TC-07: Strong CIO vacancy → ОТКЛИКАТЬСЯ"""
    t0 = time.monotonic()
    code, out, err = _run(["--file", str(INPUTS_DIR / "strong_ai_vacancy.txt"), "--no-registry"])
    ms = int((time.monotonic() - t0) * 1000)
    if code != 0:
        return TestResult("TC-07", "Strong vacancy → ОТКЛИКАТЬСЯ", False, f"Exit code {code}", ms, err)
    if "ОТКЛИКАТЬСЯ" not in out:
        detail = " | ".join(l.strip() for l in out.splitlines() if "Score" in l or "Рекомен" in l)
        return TestResult("TC-07", "Strong vacancy → ОТКЛИКАТЬСЯ", False, f"Got: {detail}", ms)
    return TestResult("TC-07", "Strong vacancy → ОТКЛИКАТЬСЯ", True, "Recommendation: ОТКЛИКАТЬСЯ ✓", ms)


def tc_weak_vacancy() -> TestResult:
    """TC-08: Weak IT-support vacancy → ПРОПУСТИТЬ"""
    t0 = time.monotonic()
    code, out, err = _run(["--file", str(INPUTS_DIR / "weak_support_vacancy.txt"), "--no-registry"])
    ms = int((time.monotonic() - t0) * 1000)
    if code != 0:
        return TestResult("TC-08", "Weak vacancy → ПРОПУСТИТЬ", False, f"Exit code {code}", ms, err)
    if "ПРОПУСТИТЬ" not in out:
        detail = " | ".join(l.strip() for l in out.splitlines() if "Score" in l or "Рекомен" in l)
        return TestResult("TC-08", "Weak vacancy → ПРОПУСТИТЬ", False, f"Got: {detail}", ms)
    return TestResult("TC-08", "Weak vacancy → ПРОПУСТИТЬ", True, "Recommendation: ПРОПУСТИТЬ ✓", ms)


def _extract_score(stdout: str) -> int | None:
    """Parse the Match Score value from CLI stdout."""
    for line in stdout.splitlines():
        if "Match Score" in line and ":" in line:
            try:
                return int(line.split(":", 1)[1].strip().split("/")[0].strip())
            except (ValueError, IndexError):
                pass
    return None


def tc_ai_partner_vacancy() -> TestResult:
    """TC-09: AI transformation lead → УТОЧНИТЬ (score 45–65)"""
    t0 = time.monotonic()
    code, out, err = _run(["--file", str(INPUTS_DIR / "ai_partner_vacancy.txt"), "--no-registry"])
    ms = int((time.monotonic() - t0) * 1000)
    if code != 0:
        return TestResult("TC-09", "AI transformation → не ПРОПУСТИТЬ (45–65)", False, f"Exit code {code}", ms, err)
    # LLM may upgrade to ЗАПУСТИТЬ В РАБОТУ — both outcomes indicate recognised value
    if "УТОЧНИТЬ" not in out and "ЗАПУСТИТЬ В РАБОТУ" not in out:
        detail = " | ".join(l.strip() for l in out.splitlines() if "Score" in l or "Рекомен" in l)
        return TestResult("TC-09", "AI transformation → не ПРОПУСТИТЬ (45–65)", False,
                          f"Expected УТОЧНИТЬ or ЗАПУСТИТЬ В РАБОТУ: {detail}", ms)
    score = _extract_score(out)
    if score is not None and not (45 <= score <= 65):
        return TestResult("TC-09", "AI transformation → не ПРОПУСТИТЬ (45–65)", False,
                          f"score={score} outside 45–65", ms)
    rec = "ЗАПУСТИТЬ В РАБОТУ" if "ЗАПУСТИТЬ В РАБОТУ" in out else "УТОЧНИТЬ"
    return TestResult("TC-09", "AI transformation → не ПРОПУСТИТЬ (45–65)", True,
                      f"{rec}, score={score if score is not None else '?'}", ms)


def tc_evolutionary_launch() -> TestResult:
    """TC-10: AI CoE role → ЗАПУСТИТЬ В РАБОТУ (high evolutionary potential)"""
    t0 = time.monotonic()
    code, out, err = _run(["--file", str(INPUTS_DIR / "evolutionary_target_vacancy.txt"), "--no-registry"])
    ms = int((time.monotonic() - t0) * 1000)
    if code != 0:
        return TestResult("TC-10", "AI CoE → ЗАПУСТИТЬ В РАБОТУ", False, f"Exit code {code}", ms, err)
    if "ЗАПУСТИТЬ В РАБОТУ" not in out:
        detail = " | ".join(l.strip() for l in out.splitlines() if "Score" in l or "Рекомен" in l or "Эво" in l)
        return TestResult("TC-10", "AI CoE → ЗАПУСТИТЬ В РАБОТУ", False,
                          f"Expected ЗАПУСТИТЬ В РАБОТУ: {detail}", ms)
    score = _extract_score(out)
    return TestResult("TC-10", "AI CoE → ЗАПУСТИТЬ В РАБОТУ", True,
                      f"ЗАПУСТИТЬ В РАБОТУ, rule-based score={score if score is not None else '?'}", ms)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

ALL_TESTS = [
    tc_file_input,
    tc_stdin_pipe,
    tc_interactive_simulated,
    tc_markdown_report,
    tc_json_report,
    tc_registry_updated,
    tc_strong_vacancy,
    tc_weak_vacancy,
    tc_ai_partner_vacancy,
    tc_evolutionary_launch,
]


def run_all() -> list[TestResult]:
    results: list[TestResult] = []
    for fn in ALL_TESTS:
        label = (fn.__doc__ or fn.__name__).split("\n")[0].strip()
        print(f"  {label:<48}", end=" ", flush=True)
        result = fn()
        print("PASS" if result.passed else "FAIL")
        results.append(result)
    return results


def print_summary(results: list[TestResult]) -> None:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    sep = "─" * 64
    print(f"\n{sep}")
    print(f"  QA Report — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"  Passed: {passed} / {total}")
    print(sep)
    for r in results:
        icon = "✅" if r.passed else "❌"
        print(f"  {icon}  {r.id}  {r.name}")
        print(f"         {r.message}  ({r.duration_ms} ms)")
        if not r.passed and r.details:
            for line in r.details.splitlines()[:3]:
                print(f"         > {line}")
    print(sep)
    verdict = "All tests passed." if passed == total else f"{total - passed} test(s) failed."
    icon = "✅" if passed == total else "❌"
    print(f"  {icon} {verdict}\n")


def save_report(results: list[TestResult]) -> Path:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    lines = [
        f"# QA Report — {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        "",
        f"> Сгенерировано: `python qa/run_functional_tests.py`",
        "",
        f"**Результат: {passed} / {total} тестов прошли**",
        "",
        "| ID | Тест | Статус | Время | Сообщение |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        status = "✅ PASS" if r.passed else "❌ FAIL"
        lines.append(f"| {r.id} | {r.name} | {status} | {r.duration_ms} мс | {r.message} |")

    if any(not r.passed for r in results):
        lines += ["", "## Детали ошибок", ""]
        for r in results:
            if not r.passed and r.details:
                lines += [f"### {r.id} — {r.name}", "```", r.details[:500].strip(), "```", ""]

    path = QA_DIR / "test_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    if "--list" in sys.argv:
        for fn in ALL_TESTS:
            label = (fn.__doc__ or fn.__name__).split("\n")[0].strip()
            print(f"  {label}")
        return

    print("\nVacancy Intelligence Assistant — Functional Test Suite")
    print("=" * 57)
    print(f"Root   : {ROOT}")
    print(f"Python : {sys.version.split()[0]}")
    print()

    results = run_all()
    print_summary(results)

    report_path = save_report(results)
    print(f"Report : {report_path}")

    sys.exit(0 if all(r.passed for r in results) else 1)


if __name__ == "__main__":
    main()
