"""
Batch vacancy discovery & triage — hh.ru search pipeline.

Runs the configured search queries against hh.ru, fetches full descriptions
for vacancies not seen before, and triages them with the deterministic
rule-based scorer. LLM analysis is intentionally NOT run here: a batch of
50 vacancies would mean 50 paid Sonnet calls; instead the user opens the
full analysis for shortlisted items one by one.

State (already-triaged vacancies) persists in output/hh_search_state.json,
so repeated runs only process genuinely new postings.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from agents import hh_api
from agents.intake import from_json
from core.analyzers.rule_based import RuleBasedAnalyzer
from core.models import CandidateProfile

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "hh_search.yaml"
STATE_PATH = BASE_DIR / "output" / "hh_search_state.json"

DEFAULT_CONFIG: dict = {
    "queries": [
        "CIO",
        "CDTO",
        "Директор по информационным технологиям",
        "Директор по ИТ",
        "Директор по цифровой трансформации",
        "ИТ-директор",
    ],
    "area": 113,            # Россия
    "search_field": "name", # искать только в названии вакансии
    "max_pages_per_query": 1,
    "max_new_per_run": 30,  # сколько новых вакансий обрабатывать за один запуск
}


@dataclass
class TriageItem:
    hh_id: str
    title: str = ""
    company: str = ""
    area: str = ""
    salary: str = ""
    url: str = ""
    published_at: str = ""
    score: int = 0
    recommendation: str = ""
    key_matches: list[str] = field(default_factory=list)
    triaged_at: str = ""
    error: str = ""


@dataclass
class SearchRunResult:
    items: list[TriageItem]        # all known items, best score first
    new_count: int                 # triaged in this run
    found_total: int               # ids matched by queries this run
    skipped_backlog: int           # new ids left for the next run (max_new cap)
    errors: list[str] = field(default_factory=list)


def load_search_config() -> dict:
    """Read config/hh_search.yaml, falling back to defaults per key."""
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            user_cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            cfg.update({k: v for k, v in user_cfg.items() if v is not None})
        except yaml.YAMLError:
            pass  # malformed config → defaults keep the pipeline alive
    return cfg


def _load_state() -> dict[str, dict]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_state(state: dict[str, dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def run_search(
    profile: CandidateProfile,
    queries: list[str] | None = None,
    rescan: bool = False,
) -> SearchRunResult:
    """
    Execute the discovery pipeline:
      queries → vacancy ids → (new only) full fetch → rule-based triage.

    rescan=True re-triages everything found, ignoring saved state
    (useful after editing the scoring profile).
    """
    cfg = load_search_config()
    queries = [q for q in (queries or cfg["queries"]) if q and q.strip()]
    errors: list[str] = []

    # ── Collect ids across queries (order preserved, deduped) ──
    all_ids: list[str] = []
    seen_ids: set[str] = set()
    for q in queries:
        try:
            ids = hh_api.search_vacancy_ids(
                q.strip(),
                area=cfg.get("area"),
                max_pages=int(cfg.get("max_pages_per_query", 1)),
                search_field=cfg.get("search_field", "name"),
            )
        except hh_api.HHApiError as exc:
            errors.append(f"Запрос «{q}»: {exc}")
            continue
        for vid in ids:
            if vid not in seen_ids:
                seen_ids.add(vid)
                all_ids.append(vid)

    # ── Determine which ids need triage ──
    state = {} if rescan else _load_state()
    # Drop error records from earlier runs (and legacy state files):
    # a failed fetch must not count as "seen", otherwise it is never retried.
    state = {vid: rec for vid, rec in state.items() if not rec.get("error")}
    new_ids = [vid for vid in all_ids if vid not in state]
    max_new = int(cfg.get("max_new_per_run", 30))
    to_fetch = new_ids[:max_new]
    skipped_backlog = len(new_ids) - len(to_fetch)

    # ── Fetch + triage new vacancies ──
    analyzer = RuleBasedAnalyzer()
    fetched, fetch_errors, rate_limited = hh_api.fetch_vacancies_batch(to_fetch)

    # Failed ids are reported but NOT persisted — next run retries them.
    unattempted = len(to_fetch) - len(fetched) - len(fetch_errors)
    skipped_backlog += len(fetch_errors) + unattempted
    if rate_limited:
        errors.append(
            "hh.ru временно ограничил частоту запросов — загрузка остановлена. "
            f"Не обработано вакансий: {len(fetch_errors) + unattempted}. "
            "Подождите несколько минут и запустите поиск снова — "
            "они будут обработаны автоматически."
        )
    for vid, msg in list(fetch_errors.items())[:5]:
        errors.append(f"Вакансия {vid}: {msg}")
    if len(fetch_errors) > 5:
        errors.append(f"… и ещё {len(fetch_errors) - 5} вакансий с ошибками загрузки")

    for vid, data in fetched.items():
        vi = from_json(data, source_name=f"hh.ru:{vid}")
        analysis = analyzer.analyze(vi.normalized_text, profile)
        state[vid] = asdict(TriageItem(
            hh_id=vid,
            title=vi.title or data.get("name", ""),
            company=vi.company,
            area=vi.location,
            salary=vi.salary,
            url=vi.url or f"{hh_api.HH_SITE_BASE}/vacancy/{vid}",
            published_at=str(data.get("published_at", ""))[:10],
            score=analysis.match_score,
            recommendation=analysis.recommendation.value,
            key_matches=analysis.key_matches[:6],
            triaged_at=datetime.now().isoformat(timespec="seconds"),
        ))

    _save_state(state)

    items = [TriageItem(**rec) for rec in state.values()]
    items.sort(key=lambda t: (t.error != "", -t.score))
    return SearchRunResult(
        items=items,
        new_count=len(fetched),
        found_total=len(all_ids),
        skipped_backlog=skipped_backlog,
        errors=errors,
    )
