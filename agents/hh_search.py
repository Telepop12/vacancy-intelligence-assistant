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
    "order_by": "publication_time",  # свежие первыми — критично для мониторинга
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
    source: str = ""          # "" = поиск hh; "mail:hh" / "mail:linkedin" = почтовый радар
    resume_variant: str = ""  # для каких резюме площадка подобрала вакансию (из темы письма)


@dataclass
class SearchRunResult:
    items: list[TriageItem]        # all known items, best score first
    new_count: int                 # triaged in this run
    found_total: int               # ids matched by queries this run
    skipped_backlog: int           # new ids left for the next run (max_new cap)
    errors: list[str] = field(default_factory=list)
    new_ids: list[str] = field(default_factory=list)  # затриажены именно в этом прогоне


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


def make_triage_item(
    profile: CandidateProfile,
    data: dict,
    vid: str,
    analyzer: RuleBasedAnalyzer | None = None,
    source: str = "",
    resume_variant: str = "",
) -> TriageItem:
    """Score one vacancy intake dict into a TriageItem (no LLM)."""
    analyzer = analyzer or RuleBasedAnalyzer()
    vi = from_json(data, source_name=f"vacancy:{vid}")
    analysis = analyzer.analyze(vi.normalized_text, profile)
    default_url = f"{hh_api.HH_SITE_BASE}/vacancy/{vid}" if str(vid).isdigit() else ""
    return TriageItem(
        hh_id=vid,
        title=vi.title or data.get("name", ""),
        company=vi.company or data.get("employer", ""),
        area=vi.location,
        salary=vi.salary,
        url=vi.url or data.get("alternate_url", "") or default_url,
        published_at=str(data.get("published_at", ""))[:10],
        score=analysis.match_score,
        recommendation=analysis.recommendation.value,
        key_matches=analysis.key_matches[:6],
        triaged_at=datetime.now().isoformat(timespec="seconds"),
        source=source,
        resume_variant=resume_variant,
    )


def remove_from_state(vid: str) -> None:
    state = _load_state()
    if state.pop(str(vid), None) is not None:
        _save_state(state)


def get_state_item(vid: str) -> dict | None:
    return _load_state().get(str(vid))


def register_vacancy(
    profile: CandidateProfile,
    data: dict,
    vid: str,
    source: str = "",
    resume_variant: str = "",
) -> TriageItem:
    """Triage a single vacancy and add it to the shared search state."""
    item = make_triage_item(
        profile, data, vid, source=source, resume_variant=resume_variant,
    )
    state = _load_state()
    state[vid] = asdict(item)
    _save_state(state)
    return item


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
    # ord_by — параметр сортировки сайта hh (publication_time = свежие первыми).
    # Без него hh сортирует «по соответствию»: стабильный топ-50, где новые
    # вакансии могут вообще не появиться на первой странице.
    extra_params = (
        {"ord_by": cfg["order_by"]} if cfg.get("order_by") else None
    )
    for q in queries:
        try:
            ids = hh_api.search_vacancy_ids(
                q.strip(),
                area=cfg.get("area"),
                max_pages=int(cfg.get("max_pages_per_query", 1)),
                search_field=cfg.get("search_field", "name"),
                extra_params=extra_params,
            )
        except hh_api.HHApiError as exc:
            errors.append(f"Запрос «{q}»: {exc}")
            continue
        for vid in ids:
            if vid not in seen_ids:
                seen_ids.add(vid)
                all_ids.append(vid)

    # ── Determine which ids need triage ──
    # State is NEVER dropped wholesale: a rescan simply re-fetches everything
    # found by the queries. Otherwise rescan + rate limit = lost base
    # (наблюдалось вживую: 423 на все запросы стёрли 49 вакансий).
    state = _load_state()
    # Drop error records from earlier runs (and legacy state files):
    # a failed fetch must not count as "seen", otherwise it is never retried.
    state = {vid: rec for vid, rec in state.items() if not rec.get("error")}
    new_ids = list(all_ids) if rescan else [vid for vid in all_ids if vid not in state]
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

    from agents import vacancy_store
    for vid, data in fetched.items():
        prev = state.get(vid) or {}  # rescan не должен стирать пометку почтового радара
        state[vid] = asdict(make_triage_item(
            profile, data, vid, analyzer=analyzer,
            source=prev.get("source", ""),
            resume_variant=prev.get("resume_variant", ""),
        ))
        vacancy_store.save_vacancy(data, vid)  # cache: no repeat hh fetches

    _save_state(state)

    items = [TriageItem(**rec) for rec in state.values()]
    items.sort(key=lambda t: (t.error != "", -t.score))
    return SearchRunResult(
        items=items,
        new_count=len(fetched),
        found_total=len(all_ids),
        skipped_backlog=skipped_backlog,
        errors=errors,
        new_ids=list(fetched.keys()),
    )
