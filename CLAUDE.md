# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands run from `vacancy_ai_assistant/` directory.

**Start web server (development):**
```
uvicorn web.app:app --reload --port 8000
```

**Start via Docker:**
```
docker compose up --build
```

**Run all functional tests:**
```
python qa/run_functional_tests.py
```

**List tests without running:**
```
python qa/run_functional_tests.py --list
```

**CLI vacancy analysis:**
```
python main.py --file data/sample_vacancy.txt
python main.py --file data/sample_vacancy.txt --no-registry
```

**Smoke test (server must be running):**
```
python web/smoke_test.py
```

## API Key

Create `.env` in `vacancy_ai_assistant/`:
```
ANTHROPIC_API_KEY=sk-ant-...
```

All LLM calls degrade gracefully to rule-based fallbacks when the key is absent or invalid.

## Architecture

The system has four independent layers that compose at the web layer (`web/app.py`):

```
agents/intake.py          — Vacancy normalization (text/file/html/json/url → VacancyInput)
core/                     — Vacancy analysis (keyword scoring + LLM semantic analysis)
agents/resume_intelligence.py — Resume parsing → ResumeProfile
agents/career_match.py    — Resume × Vacancy → CareerMatchResult (LLM, Sonnet)
```

**Data flow for `/match` (main use case):**
1. `from_text()` / `from_file()` → `VacancyInput` (normalized, with intake confidence)
2. `load_resume()` + `analyze_resume()` → `ResumeProfile` (rule-based + Haiku LLM)
3. `analyze(vacancy, profile)` → `VacancyAnalysis` (keyword score, evolutionary potential, DI layer)
4. `career_match(vacancy, resume, keyword_score)` → `CareerMatchResult` (Sonnet, full career analysis)
5. `match_result.html` renders dual-mode dashboard (Interview / Analyst modes)

**Rule for LLM model selection:**
- `claude-sonnet-4-6` — all LLM calls: resume intelligence, career match, DI layer
- Haiku was tried for resume extraction but failed to hold full career context across companies

## Key Design Decisions

**Intake layer is mandatory.** `analyze()` and `career_match()` never receive raw text directly — all input goes through `agents/intake.py` first. Adding a new source (e.g., hh.ru API) means adding one `from_X()` function in intake; analysis layers don't change.

**`from_url()` is a stub.** Currently returns `IntakeConfidence.LOW` error. Implementation plan: detect `hh.ru/vacancy/{id}`, call `https://api.hh.ru/vacancies/{id}` (no auth), pipe JSON to existing `from_json()`.

**DOCX resumes are converted to Markdown** inside `_from_docx()` using paragraph style names (`Heading 1` → `#`, list items → `-`). This enables `marked.js` rendering in the browser and preserves structure for LLM parsing.

**Full resume text is passed to Sonnet without truncation.** Sonnet has a 200K token context. Truncating the resume (as done in earlier versions) caused career match to analyze only the last job. `resume.raw_text` is used uncut.

**`parse_roles_history()` + `format_roles_for_prompt()`** extract structured career positions from raw text using date-range regexes (`_YEAR_RANGE`). The prompt instructs Sonnet to cite every company with the format `"В [Компания] ([период]) ..."` — without this constraint, the model defaults to analyzing only the most recent position.

**Scoring architecture:** `core/analyzers/` has `BaseAnalyzer → RuleBasedAnalyzer → HybridAnalyzer → ClaudeAnalyzer`. The `analyze()` function in `core/analyzer.py` uses `HybridAnalyzer` by default. Recommendation can be overridden by `recommendation_engine.synthesize()` based on evolutionary potential (a low keyword score + high evolutionary potential → `ЗАПУСТИТЬ В РАБОТУ`).

**Template helpers passed as callables.** In `web/app.py`, `action_color` and `p_css` are passed to Jinja2 as function references (`"action_color": _action_color`), not pre-called values. Call them in templates: `{{ action_color(label) }}`.

**Language policy:** All LLM system prompts include a Russian language instruction block forbidding English professional jargon. Allowed exceptions: AI, ERP, MLOps, ROI, P&L, KPI, CEO, CIO, CTO, M&A, MBA. This applies to both `resume_intelligence.py` and `career_match.py`.

## Testing Notes

QA tests in `run_functional_tests.py` directly import from `agents/` and `core/`. The file adds `vacancy_ai_assistant/` to `sys.path` at startup — tests must be run as `python qa/run_functional_tests.py` from `vacancy_ai_assistant/`, not from `qa/`.

TC-30..32 (Career Match tests) make live LLM calls and require `ANTHROPIC_API_KEY`. They fall back gracefully but `career_match_score` will equal `keyword_score` when the key is absent.

`qa/sample_inputs/sample_resume.txt` is required for TC-20..24, TC-30..32. If this file doesn't exist, those tests fail with a FileNotFoundError.
