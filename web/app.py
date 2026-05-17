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
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agents.career_match import career_match
from agents.intake import from_file, from_html, from_json, from_text, from_url
from agents.resume_intelligence import ResumeProfile, analyze_resume, load_resume
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


def _confidence_color(confidence: str) -> str:
    return {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(confidence, "yellow")


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
                request, "index.html",
                context={
                    "profile_name": _profile.name,
                    "error": f"Неподдерживаемый тип файла: {suffix}. Принимаются .txt, .md, .json",
                },
            )
        content = await vacancy_file.read()
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
            request, "index.html",
            context={
                "profile_name": _profile.name,
                "error": error,
                "prefill": vacancy_text,
            },
        )

    analysis = analyze(vacancy, _profile)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path   = save_markdown(analysis, OUTPUT_DIR)
    json_path = save_json(analysis, OUTPUT_DIR)
    update_registry(analysis, REGISTRY)

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
        },
    )


def _positioning_css(level: str) -> str:
    return {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(level, "yellow")


# ---------------------------------------------------------------------------
# Resume Intelligence routes
# ---------------------------------------------------------------------------

@app.get("/resume", response_class=HTMLResponse)
async def resume_page(request: Request):
    return templates.TemplateResponse(request, "resume.html", context={})


@app.post("/resume/analyze", response_class=HTMLResponse)
async def resume_analyze(
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
            })
        import tempfile
        content = await resume_file.read()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            text, src_type = load_resume(tmp_path)
            src_name = resume_file.filename
        except Exception as exc:
            return templates.TemplateResponse(request, "resume.html", context={
                "error": f"Ошибка чтения файла: {exc}",
            })
        finally:
            tmp_path.unlink(missing_ok=True)
    elif resume_text.strip():
        text, src_type, src_name = resume_text.strip(), "text", "paste"
    else:
        return templates.TemplateResponse(request, "resume.html", context={
            "error": "Загрузите файл резюме или вставьте текст.",
        })

    profile = analyze_resume(text, source_file=src_name, source_type=src_type)

    return templates.TemplateResponse(request, "resume_result.html", context={
        "profile":   profile,
        "p_css":     _positioning_css,
    })


# ---------------------------------------------------------------------------
# Career Match routes
# ---------------------------------------------------------------------------

@app.get("/match", response_class=HTMLResponse)
async def match_page(request: Request):
    return templates.TemplateResponse(request, "match.html", context={})


@app.post("/match/analyze", response_class=HTMLResponse)
async def match_analyze(
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
        content = await vacancy_file.read()
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
            content = await resume_file.read()
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
        "action_color":   _action_color(match_result.recommendation_label),
        "p_css":          _positioning_css,
    })


@app.get("/output/{filename}")
async def download(filename: str):
    """Serve generated report files for download."""
    path = OUTPUT_DIR / filename
    if not path.exists() or path.suffix not in {".md", ".json"}:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), filename=filename)
