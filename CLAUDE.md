# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Vacancy Intelligence Assistant — a self-hosted, single-user job-search pipeline for a
CIO / CTO / CDTO candidate: find vacancies (hh.ru search, e-mail alerts, employer career pages)
→ score them (rule-based triage, LLM career match on demand) → generate application material
(cover letter, resume variant, interview prep). Sending an application is always a manual step
by the user. UI, LLM output and most docs are in Russian; the user is the customer.

Documentation map — keep in sync:

- [README.md](README.md) — user-facing usage and feature descriptions.
- [ARCHITECTURE.md](ARCHITECTURE.md) — design decisions and *why*. Update on any design-level decision.
- [BACKLOG.md](BACKLOG.md) — sprint plan: next sprint, queue, rejected ideas. Update when the plan changes.
- [CHANGELOG.md](CHANGELOG.md) — one section per sprint/date. Add a section when closing a sprint.
- [DOCS-INDEX.md](DOCS-INDEX.md) — registry of all docs; register new docs there.

Work runs in sprints: the customer sets a task → sprint is built → customer acceptance → commit →
next sprint. Do not start the next sprint before the previous one is accepted.

## Commands

All commands run from `vacancy_ai_assistant/`. Python 3.11+ (Docker image is 3.11).
**On this Windows host bare `python` is 3.13 without the dependencies — use `py -3.14 -m ...`.**

```
pip install -r requirements.txt
```

Web server (FastAPI):

```
uvicorn web.app:app --reload --port 8000     # local
docker compose up --build -d                 # Docker; output/, config/, data/ are volumes
```

`config/` and `data/` are mounted into the container, so editing a YAML (model, search queries,
monitor interval, target companies) needs only a restart. Code changes need a rebuild.

Tests — pytest, offline by default (205 collected, 8 marked `llm`, offline run takes seconds):

```
pytest qa/                                   # full offline suite
pytest qa/ -m llm                            # only tests that make live Claude calls (need the key)
pytest qa/test_hh.py -q                      # one file
pytest qa/test_intake.py::test_name          # one test
pytest qa/ -k "intake or resume"
```

Legacy end-to-end runner (spawns `main.py` subprocesses for TC-01…TC-32, writes `qa/test_report.md`,
appends to the real `output/registry.csv`):

```
python qa/run_functional_tests.py            # --list prints the cases without running
```

Smoke test against a running server: `python web/smoke_test.py`.

CLI entry points:

```
python main.py --file data/sample_vacancy.txt [--no-registry]   # analyze one vacancy (stdin works too)
python -m agents.mail_radar emails.json                          # ingest LinkedIn/hh alert e-mails (JSON list)
python -m agents.mail_radar --check-linkedin [N]                 # LinkedIn lead liveness — run on the HOST, not in Docker
python -m agents.career_watch [Company ...]                      # crawl career pages from config/target_companies.yaml
python -m agents.cv_export [--lang ru] [--no-pdf] [--out DIR]    # executive CV from data/resume/cv_<lang>.yaml (PDF needs Word)
```

Environment: `.env` in this directory holds `ANTHROPIC_API_KEY` (all LLM features degrade to
rule-based content without it) and optional `TG_BOT_TOKEN` for monitor alerts. There is no hh.ru
token: hh.ru closed its API to applicants in December 2025 and dev.hh.ru registers employers only.
Do not suggest obtaining one.

## Architecture

Layers, composed in `web/app.py` (FastAPI + Jinja2, server-rendered, no SPA):

```
SOURCES     agents/hh_search.py      search queries → new ids → fetch → rule-based triage
            agents/mail_radar.py     LinkedIn/hh alert e-mails → leads (hh leads fetched; LinkedIn leads stay cards)
            agents/career_watch.py   employer career pages or hh employer search → new postings → triage
            web  POST /vacancy/add   manual: hh link and/or pasted text
            agents/monitor.py        background thread: search → digest → auto-packages (capped) → Telegram
STORE       agents/vacancy_store.py  output/vacancies/{vid}.json cache, favorites, dismissed
            agents/hh_search.py      output/hh_search_state.json — the triage ledger every source registers into
ANALYSIS    agents/intake.py         any input → VacancyInput (normalized text, metadata, confidence)
            core/                    keyword scoring → analyzers → recommendation_engine.synthesize()
            agents/resume_intelligence.py   resume → ResumeProfile
            agents/career_match.py          resume × vacancy → CareerMatchResult (LLM)
GENERATORS  agents/resume_variants.py       5 permanent resume archetypes (cio/cto/cdto/caio/universal)
            agents/application_package.py   cover letter + variant choice + hh AI-screener Q&A
            agents/interview_prep.py        8-stage prep package: process map, questions, presentation, stories, 100 days, agenda, blitz, improvements, cheat sheet; per-block ask-AI
            agents/prep_jobs.py             background prep build (thread per package), progress for /prep/{vid}/status, resume of failed optional stages
            agents/interview_kb.py          keyword-addressed slices of data/interview_kb/ for prep prompts; company process profiles
            agents/cv_export.py             English executive CV, DOCX → PDF
LLM         core/llm.py              the only Anthropic client; model/effort in config/llm.yaml
```

**Vacancy identity (`vid`).** Whatever the source, a vacancy ends up in the store and as a row in
the triage ledger with a `source` tag (`hh`, `mail:hh`, `career:<Company>`, manual). `vid` is the
numeric hh id, `m<timestamp>` for manual entries, `c<sha1(url)>` for career-page finds.
`vacancy_store.resolve_vacancy(vid)` returns the cached dict or fetches from hh once;
`hh_search.register_vacancy(profile, data, vid)` scores it and writes the ledger row. All
per-vacancy pages (`/vacancy/{vid}`, `/analyze/{vid}`, `/package/{vid}`, `/prep/{vid}`) key on
this id; the `/.../hh/{id}` routes are legacy redirects.

**Main flow `/match`:** `from_text()/from_file()/from_url()` → `load_resume()` +
`analyze_resume()` → `analyze(vacancy, profile)` → `career_match(...)` → `match_result.html`
(graph "cockpit" view by default, `web/static/cockpit_graph.js`).

**Batch flows are LLM-free.** Search, radar, career watch and the monitor triage with
`RuleBasedAnalyzer` only. Paid LLM analysis happens per vacancy on an explicit user action, or in
the monitor capped by `max_packages_per_cycle`.

**Generators cache to `output/<kind>/{id}.json` + `.md`** (`resume_variants/`, `applications/`,
`prep/`). Pages load the saved artifact unless `?regenerate=1`.

**State is files under `output/`** (git-ignored, Docker volume): `registry.csv`,
`hh_search_state.json`, `hh_cooldown.json`, `mail_radar_state.json`, `career_watch_state.json`
+ `career_watch/`, `monitor_digest.json`, `tg_state.json`, `favorites.json`, `dismissed.json`,
`vacancies/`. `data/resume/` (canonical resume, facts base, CV content) is git-ignored personal
data too.

## Rules that shape changes

**Intake is mandatory.** `analyze()` and `career_match()` never receive raw text; every source
goes through a `from_X()` in `agents/intake.py`. New source = new `from_X()`; analysis layers stay
untouched.

**One LLM gateway.** Every model call goes through `core.llm.call_json(system, prompt, ...)`.
Never instantiate `anthropic.Anthropic` elsewhere. The gateway reads the key from env or `.env`,
uses `anthropic.DefaultHttpxClient(trust_env=False)` (SDK 1.x moved to httpx2, a hand-built httpx
client breaks), streams every request (`messages.stream()` + `get_final_message()`, so long
answers don't hit the HTTP timeout), takes the first `text` block because Sonnet 5 returns a
thinking block first, enforces `min_max_tokens`, treats `stop_reason == "max_tokens"` as
truncation, retries once on truncated or invalid JSON, raises on `refusal`, and retries once more
when any `banned_substrings` appear (style guard). Model `claude-sonnet-5`, effort `medium` — set in
`config/llm.yaml`, change it there, not in code. The `models:` map there overrides the model per
call `purpose` (`prep` → `claude-opus-5` for the interview-prep generator, customer decision
2026-09-22); pass `purpose=` from a generator's `_call_llm` wrapper, never hardcode a model id.

**Analyzer selection is per call.** `core/analyzer.py::analyze()` builds `ClaudeAnalyzer` when a
key is present, else `HybridAnalyzer` (deterministic content plus placeholders for LLM fields).
Hierarchy in `core/analyzers/`: `BaseAnalyzer → RuleBasedAnalyzer → HybridAnalyzer →
ClaudeAnalyzer`. `recommendation_engine.synthesize()` may override the score-based recommendation
(low keyword score + high evolutionary potential → `ЗАПУСТИТЬ В РАБОТУ`).

**hh.ru is accessed only through public HTML pages** — JSON-LD `JobPosting` on vacancy pages, serp
cards on search pages. The anti-bot measures in `agents/hh_api.py` are deliberate: one shared
cookie session, randomized pauses (`_REQUEST_DELAY` plus jitter), one retry on 403/429, stop after
3 consecutive blocks, and a 30-minute cooldown persisted in `output/hh_cooldown.json`. Do not
remove delays or raise batch sizes casually. Search ids come only from `serp-item__title` cards —
a page-wide regex once pulled in "similar vacancies" noise. Failed fetches are not marked as seen,
so they retry on the next run.

**LinkedIn is never scraped with the user's account.** LinkedIn radar leads stay as cards until
the user pastes the text. Liveness checks hit only the public guest page, from the host (the
container has no LinkedIn access), in small batches, and stop at the first sign of blocking.

**Resume facts hierarchy.** Generators may re-accent, never invent. The canonical resume in
`data/resume/` is the master; `data/resume/facts.md` adds only items marked ✅ (🚫 sections are
ignored). Interview stories come only from `data/resume/stories.md` (personal, git-ignored); while it
is empty the prep generator emits skeletons labelled «каркас из резюме», never invented stories.
Because an hh.ru application uses a resume that already exists in the account, the
per-vacancy artifact is the cover letter (~120–150 words: about me → why me → next step), not a
new resume.

**Full resume text goes to the LLM uncut.** `parse_roles_history()` + `format_roles_for_prompt()`
in `agents/resume_intelligence.py` add a positions list, and the prompt requires citing every
company as «В [Компания] ([период]) …». Without this the model analyzes only the last job.

**Prep prompts read the knowledge base through `agents/interview_kb.py`.** Sections are looked up by
header keywords, never by section numbers (the base is regenerated quarterly). Every excerpt starts
with `[источник: …]`; sources returned by the model are filtered against the excerpt and resolved via
`resolve_sources()`. Stages 4–6 of `build_prep()` are non-fatal: a failure lands in `stage_errors`
and the package is still saved.

**Language policy.** Every system prompt carries the Russian-only block forbidding English
professional jargon (allowed: AI, ERP, MLOps, ROI, P&L, KPI, CEO, CIO, CTO, M&A, MBA). An English
mode for the international track is planned in BACKLOG.md, not built.

**Web layer conventions.** Routes that call the LLM or the network are plain `def` (FastAPI runs
them in a threadpool, the event loop stays free); light routes are `async def`. Template helpers
(`action_color`, `p_css`) are passed as callables and called in templates:
`{{ action_color(label) }}`. Static assets are versioned in every template (`style.css?v=N`,
`cockpit_graph.js?v=N`) — bump N when editing them. The monitor scheduler starts as a daemon
thread on FastAPI startup; interval and threshold live in `config/monitor.yaml`.

**Tests never touch real state or the LLM.** `qa/conftest.py` blanks the API key for every test
not marked `@pytest.mark.llm`, including CLI subprocesses (it sets a placeholder value rather than
an empty string because Windows drops empty env vars). Tests that write state monkeypatch module
paths (`vacancy_store.STORE_DIR`, `hh_search.STATE_PATH`, `*.OUTPUT_DIR`, `monitor.DIGEST_PATH`,
`mail_radar.STATE_PATH`, ...) to `tmp_path`; follow the same pattern. Network is mocked in
`qa/test_hh.py`. Fixtures live in `qa/sample_inputs/`; `sample_resume.txt` there is required by the
resume and career-match cases.

## Environment gotchas

- **Encoding.** Source, templates and docs contain Cyrillic. Edit with tools that write UTF-8
  without BOM; a PowerShell `Set-Content` pass once corrupted every template. `main.py` and the
  test runners reconfigure stdout to UTF-8 for Windows consoles.
- **Line endings.** `.gitattributes` forces LF for all text files; Python `Path.write_text` on
  Windows emits CRLF, so normalize or let git do it.
- **Docker + pip.** Any change to `requirements.txt` invalidates the pip layer, and PyPI's CDN has
  timed out from Docker on this network. `anthropic` is pinned `>=1.7,<2` (host and image both
  1.7.0 since 2026-09-22).
- **Russian trusted root CA** (`config/certs/russian_trusted_root_ca.pem`) is added to the SSL
  context by `career_watch` for career pages of Alfa-Bank, RZD and Metalloinvest.
