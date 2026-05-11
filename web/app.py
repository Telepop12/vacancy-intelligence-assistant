"""
Web UI for Vacancy Intelligence Assistant.

Run locally:
    uvicorn web.app:app --reload --port 8000

Run via Docker:
    docker compose up --build
"""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.analyzer import analyze
from core.models import CandidateProfile, ScoringGroup
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "profile": _profile.name}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html",
        context={"profile_name": _profile.name},
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_vacancy(
    request: Request,
    vacancy_text: str = Form(...),
):
    if not vacancy_text.strip():
        return templates.TemplateResponse(
            request, "index.html",
            context={
                "profile_name": _profile.name,
                "error": "Текст вакансии не может быть пустым",
                "prefill": vacancy_text,
            },
        )

    analysis = analyze(vacancy_text.strip(), _profile)
    analysis.source_file = "web"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path   = save_markdown(analysis, OUTPUT_DIR)
    json_path = save_json(analysis, OUTPUT_DIR)
    update_registry(analysis, REGISTRY)

    display_action = analysis.recommended_action or analysis.recommendation.value
    return templates.TemplateResponse(
        request, "result.html",
        context={
            "analysis":       analysis,
            "score_color":    _score_color(analysis.match_score),
            "md_filename":    md_path.name,
            "json_filename":  json_path.name,
            "display_action": display_action,
            "action_color":   _action_color(display_action),
            "evo_level":      _evo_level(analysis.evolutionary_potential),
            "LLM_PENDING":    "Ожидает подключения LLM",
        },
    )


@app.get("/output/{filename}")
async def download(filename: str):
    """Serve generated report files for download."""
    path = OUTPUT_DIR / filename
    if not path.exists() or path.suffix not in {".md", ".json"}:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), filename=filename)
