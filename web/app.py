"""
Web UI for Vacancy Intelligence Assistant.

Run locally:
    uvicorn web.app:app --reload --port 8000

Run via Docker:
    docker compose up --build
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agents import hh_api
from agents.career_match import career_match
from agents import monitor, vacancy_store
from agents.hh_search import (
    get_state_item, load_search_config, register_vacancy,
    remove_from_state, run_search,
)
from agents.application_package import (
    build_package, letter_word_count, load_saved_package,
)
from agents.interview_prep import answer_user_question, build_prep, load_saved_prep
from agents.resume_variants import (
    generate_all, generate_variant, load_saved_variants,
    load_variants_config, resume_path,
)
from agents.intake import from_file, from_html, from_json, from_text, from_url
from agents.resume_intelligence import ResumeProfile, analyze_resume, load_resume
from core.analyzer import analyze
from core.models import CandidateProfile, ScoringGroup
from core.output_manager import cleanup_output_dir
from core.report import save_json, save_markdown, update_registry

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_WEB_DIR    = Path(__file__).resolve().parent          # web/
BASE_DIR    = _WEB_DIR.parent                          # vacancy_ai_assistant/
CONFIG_PATH = BASE_DIR / "config" / "candidate_profile.yaml"
OUTPUT_DIR  = BASE_DIR / "output"
REGISTRY    = OUTPUT_DIR / "registry.csv"

# ---------------------------------------------------------------------------
# FastAPI setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Vacancy Intelligence Assistant")

app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))

# ---------------------------------------------------------------------------
# Profile (loaded once at startup)
# ---------------------------------------------------------------------------


def _load_profile(path: Path) -> CandidateProfile:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    scoring_groups = {
        name: ScoringGroup(weight=g["weight"], keywords=g.get("keywords", []))
        for name, g in data.get("scoring_groups", {}).items()
    }
    return CandidateProfile(
        name=data["name"],
        target_roles=data.get("target_roles", []),
        scoring_groups=scoring_groups,
        red_flags=dict(data.get("red_flags", {})),
        seniority_keywords=data.get("seniority_keywords", []),
    )


_profile: CandidateProfile = _load_profile(CONFIG_PATH)


def _score_color(score: int) -> str:
    if score >= 70:
        return "green"
    if score >= 45:
        return "yellow"
    return "red"


def _action_color(action: str) -> str:
    return {
        "ОТКЛИКАТЬСЯ":        "green",
        "УТОЧНИТЬ":           "yellow",
        "ЗАПУСТИТЬ В РАБОТУ": "launch",
        "ПРОПУСТИТЬ":         "red",
    }.get(action, "yellow")


def _evo_level(potential: str) -> str:
    return {"High": "high", "Medium": "medium", "Low": "low"}.get(potential, "low")


def _confidence_color(confidence: str) -> str:
    return {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(confidence, "yellow")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "profile": _profile.name}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request, "home.html",
        context={"profile_name": _profile.name},
    )


@app.get("/vacancy", response_class=HTMLResponse)
async def vacancy_page(request: Request):
    return templates.TemplateResponse(
        request, "vacancy.html",
        context={"profile_name": _profile.name, "active_nav": "vacancy"},
    )


@app.post("/analyze", response_class=HTMLResponse)
def analyze_vacancy(  # sync: LLM-генерация уходит в threadpool FastAPI, event loop свободен
    request: Request,
    vacancy_text: str = Form(default=""),
    vacancy_url:  str = Form(default=""),
    source_type:  str = Form(default="text"),
    vacancy_file: Optional[UploadFile] = File(default=None),
):
    # ── Build VacancyInput via intake pipeline ──
    vacancy = None

    # Priority: uploaded file > URL > text area
    if vacancy_file and vacancy_file.filename:
        suffix = Path(vacancy_file.filename).suffix.lower()
        if suffix not in {".txt", ".md", ".json"}:
            return templates.TemplateResponse(
                request, "vacancy.html",
                context={
                    "profile_name": _profile.name,
                    "error": f"Неподдерживаемый тип файла: {suffix}. Принимаются .txt, .md, .json",
                    "active_nav": "vacancy",
                },
            )
        content = vacancy_file.file.read()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            vacancy = from_file(tmp_path)
            vacancy.source_name = vacancy_file.filename
        finally:
            tmp_path.unlink(missing_ok=True)

    elif vacancy_url.strip():
        vacancy = from_url(vacancy_url.strip())

    elif vacancy_text.strip():
        if source_type == "html":
            vacancy = from_html(vacancy_text.strip())
        elif source_type == "json":
            vacancy = from_json(vacancy_text.strip())
        else:
            vacancy = from_text(vacancy_text.strip())

    if not vacancy or not vacancy.normalized_text.strip():
        error = "Текст вакансии не может быть пустым"
        if vacancy and vacancy.confidence_notes:
            error = vacancy.confidence_notes[0]
        return templates.TemplateResponse(
            request, "vacancy.html",
            context={
                "profile_name": _profile.name,
                "error": error,
                "prefill": vacancy_text,
                "active_nav": "vacancy",
            },
        )

    return _render_vacancy_result(request, vacancy)


def _render_vacancy_result(request: Request, vacancy) -> HTMLResponse:
    """Run full analysis of a VacancyInput and render the result page."""
    analysis = analyze(vacancy, _profile)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path   = save_markdown(analysis, OUTPUT_DIR)
    json_path = save_json(analysis, OUTPUT_DIR)
    update_registry(analysis, REGISTRY)
    cleanup_output_dir(OUTPUT_DIR)

    display_action = analysis.recommended_action or analysis.recommendation.value
    return templates.TemplateResponse(
        request, "result.html",
        context={
            "analysis":          analysis,
            "score_color":       _score_color(analysis.match_score),
            "md_filename":       md_path.name,
            "json_filename":     json_path.name,
            "display_action":    display_action,
            "action_color":      _action_color(display_action),
            "evo_level":         _evo_level(analysis.evolutionary_potential),
            "confidence_color":  _confidence_color(analysis.intake_confidence),
            "LLM_PENDING":       "Ожидает подключения LLM",
            "active_nav":        "vacancy",
        },
    )


def _positioning_css(level: str) -> str:
    return {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(level, "yellow")


# ---------------------------------------------------------------------------
# Resume variants routes
# ---------------------------------------------------------------------------

def _variants_context() -> dict:
    from agents.resume_variants import load_published

    cfg = load_variants_config()
    rp = resume_path(cfg)
    published_dates = {
        key: load_published(vcfg)[1] for key, vcfg in cfg["variants"].items()
    }
    return {
        "cfg_variants": cfg["variants"],
        "saved": load_saved_variants(),
        "resume_file": str(rp),
        "resume_exists": rp.exists(),
        "published_dates": published_dates,
        "active_nav": "variants",
    }


@app.get("/variants", response_class=HTMLResponse)
async def variants_page(request: Request):
    return templates.TemplateResponse(request, "variants.html", context=_variants_context())


@app.post("/variants/generate", response_class=HTMLResponse)
def variants_generate(request: Request, key: str = Form(default="")):
    """Generate one variant (key given) or all of them (key empty)."""
    if key:
        result = generate_variant(key)
        errors = [result.error] if result.error else []
    else:
        results = generate_all()
        errors = [f"{k}: {v.error}" for k, v in results.items() if v.error]
    ctx = _variants_context()
    ctx["errors"] = errors
    return templates.TemplateResponse(request, "variants.html", context=ctx)


# ---------------------------------------------------------------------------
# Vacancy store routes (manual input + unified vacancy card)
# ---------------------------------------------------------------------------

def _search_page_ctx(error: str = "", notice: str = "") -> dict:
    cfg = load_search_config()
    return {
        "queries": "\n".join(cfg["queries"]),
        "area": cfg.get("area", 113),
        "error": error,
        "notice": notice,
        "active_nav": "search",
    }


@app.post("/vacancy/add", response_class=HTMLResponse)
def vacancy_add(
    request: Request,
    vac_url: str = Form(default=""),
    vac_text: str = Form(default=""),
    vac_title: str = Form(default=""),
    vac_company: str = Form(default=""),
):
    """Manually add a vacancy (hh link and/or pasted text) to the pipeline."""
    vac_url, vac_text = vac_url.strip(), vac_text.strip()
    hh_id = vacancy_store.hh_id_from_url(vac_url)

    if vac_text:
        data = vacancy_store.manual_vacancy_dict(
            vac_text, title=vac_title, company=vac_company, url=vac_url,
        )
        vid = vacancy_store.save_vacancy(data, hh_id)
    elif hh_id:
        try:
            data = vacancy_store.resolve_vacancy(hh_id)
            vid = hh_id
        except hh_api.HHApiError as exc:
            return templates.TemplateResponse(request, "search.html", context=_search_page_ctx(
                error=f"{exc} — вставьте описание вакансии текстом в это же окно.",
            ))
    else:
        return templates.TemplateResponse(request, "search.html", context=_search_page_ctx(
            error="Укажите ссылку на вакансию или вставьте её текст.",
        ))

    register_vacancy(_profile, data, vid)
    return RedirectResponse(url=f"/vacancy/{vid}", status_code=303)


@app.on_event("startup")
def _start_monitor_scheduler():
    """Фоновый мониторинг: цикл каждые interval_hours (config/monitor.yaml)."""
    import logging
    import threading
    import time as _time

    logging.getLogger("monitor").setLevel(logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.WARNING)

    def _loop():
        while True:
            cfg = monitor.load_monitor_config()
            _time.sleep(max(0.5, float(cfg.get("interval_hours", 6))) * 3600)
            if cfg.get("enabled"):
                try:
                    monitor.run_cycle(_profile)
                except Exception:
                    logging.getLogger("monitor").exception("Цикл мониторинга упал")

    threading.Thread(target=_loop, daemon=True, name="vacancy-monitor").start()


@app.get("/digest", response_class=HTMLResponse)
async def digest_page(request: Request):
    entries = list(reversed(monitor.load_digest()))
    return templates.TemplateResponse(request, "digest.html", context={
        "entries": entries,
        "cfg": monitor.load_monitor_config(),
        "tg_status": monitor.telegram_status(),
        "score_color": _score_color,
        "active_nav": "digest",
    })


@app.post("/monitor/run")
def monitor_run_now(request: Request):
    """Запустить цикл мониторинга вручную (поиск + автопакеты + алерт)."""
    result = monitor.run_cycle(_profile)
    entries = list(reversed(monitor.load_digest()))
    return templates.TemplateResponse(request, "digest.html", context={
        "entries": entries,
        "cfg": monitor.load_monitor_config(),
        "tg_status": monitor.telegram_status(),
        "score_color": _score_color,
        "run_result": result,
        "active_nav": "digest",
    })


@app.post("/favorites/toggle/{vid}")
async def favorites_toggle(vid: str):
    """Star/unstar a vacancy (called via fetch from tables and cards)."""
    if vacancy_store.is_favorite(vid):
        vacancy_store.remove_favorite(vid)
        return {"favorite": False}
    vacancy_store.add_favorite(vid)
    return {"favorite": True}


@app.post("/vacancy/{vid}/delete")
async def vacancy_delete(vid: str):
    """Remove a vacancy from favorites, cache and search state."""
    vacancy_store.delete_vacancy(vid)
    remove_from_state(vid)
    return RedirectResponse(url="/favorites", status_code=303)


@app.get("/favorites", response_class=HTMLResponse)
async def favorites_page(request: Request):
    """Saved vacancies — survive rescans; full pipeline buttons per row."""
    rows = []
    for vid in vacancy_store.list_favorites():
        rec = get_state_item(vid) or {}
        data = vacancy_store.load_vacancy(vid) or {}
        if not rec and data:
            # re-triage from cache so the row always has a score
            rec = register_vacancy(_profile, data, vid).__dict__
        rows.append({
            "vid": vid,
            "title": rec.get("title") or data.get("name") or f"Вакансия {vid}",
            "company": rec.get("company") or data.get("employer", ""),
            "area": rec.get("area") or data.get("area", ""),
            "url": rec.get("url") or data.get("alternate_url", ""),
            "score": rec.get("score", 0),
            "recommendation": rec.get("recommendation", ""),
            "key_matches": rec.get("key_matches", []),
        })
    rows.sort(key=lambda r: -r["score"])
    return templates.TemplateResponse(request, "favorites.html", context={
        "rows": rows,
        "score_color": _score_color,
        "active_nav": "favorites",
    })


@app.get("/vacancy/{vid}", response_class=HTMLResponse)
async def vacancy_card(request: Request, vid: str):
    """Unified vacancy card: triage score + full pipeline buttons."""
    from agents.hh_search import _load_state
    rec = _load_state().get(vid)
    data = vacancy_store.load_vacancy(vid)
    if rec is None and data is not None:
        rec = None  # card still renders from stored data
    if rec is None and data is None:
        raise HTTPException(status_code=404, detail="Вакансия не найдена в базе")
    return templates.TemplateResponse(request, "vacancy_card.html", context={
        "vid": vid,
        "rec": rec or {},
        "data": data or {},
        "score_color": _score_color(rec.get("score", 0)) if rec else "",
        "is_favorite": vacancy_store.is_favorite(vid),
        "active_nav": "search",
    })


# ---------------------------------------------------------------------------
# Application package routes
# ---------------------------------------------------------------------------

def _package_context(pkg) -> dict:
    return {
        "pkg": pkg,
        "word_count": letter_word_count(pkg.letter) if pkg and pkg.letter else 0,
        "active_nav": "search",
    }


@app.get("/package/hh/{vacancy_id}")
async def package_page_legacy(vacancy_id: str):
    return RedirectResponse(url=f"/package/{vacancy_id}", status_code=307)


@app.get("/package/{vid}", response_class=HTMLResponse)
def package_page(request: Request, vid: str, regenerate: bool = False):
    """Show (or generate) the application package for a stored/hh vacancy."""
    pkg = None if regenerate else load_saved_package(f"hh_{vid}")
    if pkg is None:
        try:
            data = vacancy_store.resolve_vacancy(vid)
        except hh_api.HHApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        pkg = build_package(
            vacancy_text=data.get("description", ""),
            title=data.get("name", ""),
            company=data.get("employer", ""),
            url=data.get("alternate_url", ""),
            package_id=f"hh_{vid}",
        )
    return templates.TemplateResponse(request, "package.html", context=_package_context(pkg))


# ---------------------------------------------------------------------------
# Interview prep routes
# ---------------------------------------------------------------------------

@app.get("/prep/hh/{vacancy_id}")
async def prep_page_legacy(vacancy_id: str):
    return RedirectResponse(url=f"/prep/{vacancy_id}", status_code=307)


@app.get("/prep/{vid}", response_class=HTMLResponse)
def prep_page(request: Request, vid: str, regenerate: bool = False):
    """Interview prep package for a stored/hh vacancy (independent of applying)."""
    pkg = None if regenerate else load_saved_prep(f"hh_{vid}")
    if pkg is None:
        try:
            data = vacancy_store.resolve_vacancy(vid)
        except hh_api.HHApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        pkg = build_prep(
            vacancy_text=data.get("description", ""),
            title=data.get("name", ""),
            company=data.get("employer", ""),
            url=data.get("alternate_url", ""),
            package_id=f"hh_{vid}",
        )
    return templates.TemplateResponse(
        request, "prep.html", context={"pkg": pkg, "active_nav": "search"}
    )


@app.post("/prep/{vid}/ask")
def prep_ask(vid: str, question: str = Form(default="")):
    """Answer a user-typed interviewer question; persists into the package."""
    answer_user_question(f"hh_{vid}", question)
    return RedirectResponse(url=f"/prep/{vid}#user-qa", status_code=303)


# ---------------------------------------------------------------------------
# hh.ru search routes
# ---------------------------------------------------------------------------

@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    cfg = load_search_config()
    return templates.TemplateResponse(request, "search.html", context={
        "queries":    "\n".join(cfg["queries"]),
        "area":       cfg.get("area", 113),
        "active_nav": "search",
    })


@app.post("/search/run", response_class=HTMLResponse)
def search_run(
    request: Request,
    queries: str = Form(default=""),
    rescan:  str = Form(default=""),
):
    query_list = [q.strip() for q in queries.splitlines() if q.strip()]
    result = run_search(_profile, queries=query_list or None, rescan=bool(rescan))
    return templates.TemplateResponse(request, "search_results.html", context={
        "result":       result,
        "score_color":  _score_color,
        "action_color": _action_color,
        "favorites":    set(vacancy_store.list_favorites()),
        "active_nav":   "search",
    })


@app.get("/analyze/hh/{hh_id}")
async def analyze_hh_legacy(hh_id: str):
    return RedirectResponse(url=f"/analyze/{hh_id}", status_code=307)


@app.get("/analyze/{vid}", response_class=HTMLResponse)
def analyze_vacancy_by_id(request: Request, vid: str):
    """Full analysis of a stored/hh vacancy straight from the search table."""
    try:
        data = vacancy_store.resolve_vacancy(vid)
    except hh_api.HHApiError as exc:
        return templates.TemplateResponse(
            request, "search.html", context=_search_page_ctx(error=str(exc)),
        )
    vacancy = from_json(data, source_name=f"vacancy:{vid}")
    if not vacancy.normalized_text.strip():
        return templates.TemplateResponse(
            request, "search.html",
            context=_search_page_ctx(error=f"Вакансия {vid} без текста описания"),
        )
    return _render_vacancy_result(request, vacancy)


# ---------------------------------------------------------------------------
# Resume Intelligence routes
# ---------------------------------------------------------------------------

@app.get("/resume", response_class=HTMLResponse)
async def resume_page(request: Request):
    return templates.TemplateResponse(request, "resume.html", context={"active_nav": "resume"})


@app.post("/resume/analyze", response_class=HTMLResponse)
def resume_analyze(
    request: Request,
    resume_text: str = Form(default=""),
    resume_file: Optional[UploadFile] = File(default=None),
):
    text, src_type, src_name = "", "text", "paste"

    if resume_file and resume_file.filename:
        suffix = Path(resume_file.filename).suffix.lower()
        if suffix not in {".txt", ".md", ".docx", ".pdf"}:
            return templates.TemplateResponse(request, "resume.html", context={
                "error": f"Неподдерживаемый формат: {suffix}. Принимаются .txt .md .docx .pdf",
                "active_nav": "resume",
            })
        import tempfile
        content = resume_file.file.read()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            text, src_type = load_resume(tmp_path)
            src_name = resume_file.filename
        except Exception as exc:
            return templates.TemplateResponse(request, "resume.html", context={
                "error": f"Ошибка чтения файла: {exc}",
                "active_nav": "resume",
            })
        finally:
            tmp_path.unlink(missing_ok=True)
    elif resume_text.strip():
        text, src_type, src_name = resume_text.strip(), "text", "paste"
    else:
        return templates.TemplateResponse(request, "resume.html", context={
            "error": "Загрузите файл резюме или вставьте текст.",
            "active_nav": "resume",
        })

    profile = analyze_resume(text, source_file=src_name, source_type=src_type)

    return templates.TemplateResponse(request, "resume_result.html", context={
        "profile":    profile,
        "p_css":      _positioning_css,
        "active_nav": "resume",
    })


# ---------------------------------------------------------------------------
# Career Match routes
# ---------------------------------------------------------------------------

@app.get("/match", response_class=HTMLResponse)
async def match_page(request: Request):
    return templates.TemplateResponse(request, "match.html", context={"active_nav": "match"})


@app.post("/match/analyze", response_class=HTMLResponse)
def match_analyze(
    request: Request,
    vacancy_text: str = Form(default=""),
    resume_text:  str = Form(default=""),
    vacancy_file: Optional[UploadFile] = File(default=None),
    resume_file:  Optional[UploadFile] = File(default=None),
):
    errors: list[str] = []

    # ── Resolve vacancy ──
    vacancy = None
    if vacancy_file and vacancy_file.filename:
        content = vacancy_file.file.read()
        suffix = Path(vacancy_file.filename).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            vacancy = from_file(tmp_path)
            vacancy.source_name = vacancy_file.filename
        finally:
            tmp_path.unlink(missing_ok=True)
    elif vacancy_text.strip():
        vacancy = from_text(vacancy_text.strip())

    if not vacancy or not vacancy.normalized_text.strip():
        errors.append("Вставьте текст вакансии или загрузите файл")

    # ── Resolve resume ──
    resume_profile = None
    if resume_file and resume_file.filename:
        suffix = Path(resume_file.filename).suffix.lower()
        if suffix not in {".txt", ".md", ".docx", ".pdf"}:
            errors.append(f"Неподдерживаемый формат резюме: {suffix}")
        else:
            content = resume_file.file.read()
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            try:
                text, src_type = load_resume(tmp_path)
                resume_profile = analyze_resume(text, source_file=resume_file.filename,
                                                source_type=src_type)
            except Exception as exc:
                errors.append(f"Ошибка чтения резюме: {exc}")
            finally:
                tmp_path.unlink(missing_ok=True)
    elif resume_text.strip():
        resume_profile = analyze_resume(resume_text.strip(), source_type="text")

    if not resume_profile:
        errors.append("Загрузите резюме или вставьте его текст")

    if errors:
        return templates.TemplateResponse(request, "match.html", context={
            "errors": errors,
            "prefill_vacancy": vacancy_text,
            "prefill_resume": resume_text,
            "active_nav": "match",
        })

    # ── Keyword scoring (existing pipeline) ──
    vacancy_analysis = analyze(vacancy, _profile)

    # ── Career match (LLM, resume-aware) ──
    match_result = career_match(
        vacancy=vacancy,
        resume=resume_profile,
        keyword_score=vacancy_analysis.match_score,
        keyword_rec=vacancy_analysis.recommended_action or vacancy_analysis.recommendation.value,
    )

    return templates.TemplateResponse(request, "match_result.html", context={
        "match":          match_result,
        "analysis":       vacancy_analysis,
        "resume":         resume_profile,
        "score_color":    _score_color(match_result.career_match_score),
        "kw_color":       _score_color(match_result.keyword_score),
        "action_color":   _action_color,
        "p_css":          _positioning_css,
        "active_nav":     "match",
    })


@app.get("/output/{filename:path}")
async def download(filename: str):
    """Serve generated report files for download (subfolders allowed)."""
    path = (OUTPUT_DIR / filename).resolve()
    if (
        not str(path).startswith(str(OUTPUT_DIR.resolve()))
        or not path.exists()
        or path.suffix not in {".md", ".json", ".docx"}
    ):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), filename=path.name)
