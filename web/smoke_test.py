#!/usr/bin/env python3
"""
Web UI smoke test — requires the server to be running.

Usage:
    # 1. Start the server:
    #    uvicorn web.app:app --port 8000
    #    — or —
    #    docker compose up
    #
    # 2. In another terminal:
    #    python web/smoke_test.py

Exit code: 0 = all checks passed, 1 = one or more failed.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:8000"

SAMPLE_VACANCY = """\
Директор по информационным технологиям (CIO)
Компания: Промышленный холдинг (5 000+ сотрудников)
Задачи: ИТ-стратегия, цифровая трансформация, ITSM/ITIL, 1С ERP
Руководство командой 40 человек, бюджет 300 млн руб./год
"""


def _get(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)


def _post(path: str, data: dict) -> tuple[int, str]:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def check(name: str, passed: bool, detail: str = "") -> bool:
    icon = "✅" if passed else "❌"
    line = f"  {icon}  {name}"
    if detail:
        line += f"  — {detail}"
    print(line)
    return passed


def main() -> None:
    print(f"\nWeb UI Smoke Test — {BASE}\n")
    results: list[bool] = []

    # --- GET /health ---
    code, body = _get("/health")
    try:
        data = json.loads(body)
        ok = code == 200 and data.get("status") == "ok"
        results.append(check("GET /health", ok, f"HTTP {code}, profile={data.get('profile', '?')}"))
    except Exception:
        results.append(check("GET /health", False, f"HTTP {code} / bad JSON"))

    # --- GET / (index page) ---
    code, body = _get("/")
    results.append(check(
        "GET /  (index page)",
        code == 200 and "Проанализировать" in body,
        f"HTTP {code}",
    ))

    # --- POST /analyze (valid text) ---
    code, body = _post("/analyze", {"vacancy_text": SAMPLE_VACANCY})
    results.append(check(
        "POST /analyze  (valid vacancy)",
        code == 200 and "Match Score" in body,
        f"HTTP {code}",
    ))

    # --- POST /analyze (empty text → stays on index with error) ---
    code, body = _post("/analyze", {"vacancy_text": "   "})
    results.append(check(
        "POST /analyze  (empty text → error shown)",
        code == 200 and "не может быть пустым" in body,
        f"HTTP {code}",
    ))

    # --- Score + recommendation present in result ---
    code, body = _post("/analyze", {"vacancy_text": SAMPLE_VACANCY})
    has_rec = any(
        kw in body for kw in ("ОТКЛИКАТЬСЯ", "УТОЧНИТЬ", "ПРОПУСТИТЬ")
    )
    results.append(check(
        "Result contains recommendation",
        code == 200 and has_rec,
    ))

    passed = sum(results)
    total = len(results)
    print(f"\n  Passed: {passed} / {total}")
    print(f"  {'✅ All checks passed.' if passed == total else '❌ Some checks failed.'}\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
