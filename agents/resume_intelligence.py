"""
Resume Intelligence Layer — Phase 1.

Analyzes executive CVs to build a structured intelligence profile:
  - Rule-based extraction: AI/transformation/governance signals,
    technology domains, industries, years of experience
  - LLM semantic layer: strategic positioning, trajectory mapping,
    strongest assets, weak visibility areas, positioning levels

All conclusions are explainable: every inference links back to
the specific text fragments that triggered it.

Future-ready for: resume adaptation, LinkedIn generation,
interview prep, executive bio, outreach generation.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PositioningLevel(str, Enum):
    LOW    = "LOW"
    MEDIUM = "MEDIUM"
    HIGH   = "HIGH"


# ---------------------------------------------------------------------------
# Resume Profile Schema
# ---------------------------------------------------------------------------

@dataclass
class ResumeProfile:
    """
    Structured intelligence profile extracted from an executive CV.
    Single source of truth for all downstream resume-related layers.
    """
    # Source
    raw_text:    str
    source_file: str = ""
    source_type: str = ""   # txt / md / docx / pdf

    # Extracted structured data
    full_name:              str = ""
    roles_history:          list[dict[str, str]] = field(default_factory=list)
    years_experience:       int = 0
    industries:             list[str] = field(default_factory=list)

    # Intelligence signals (rule-based)
    ai_signals:             list[str] = field(default_factory=list)
    governance_signals:     list[str] = field(default_factory=list)
    transformation_experience: list[str] = field(default_factory=list)
    technology_domains:     list[str] = field(default_factory=list)
    operational_scope:      list[str] = field(default_factory=list)
    innovation_signals:     list[str] = field(default_factory=list)
    business_signals:       list[str] = field(default_factory=list)

    # Leadership & scale signals (rule-based)
    leadership_scope:       str = ""   # individual / team / division / company / group
    organizational_scale:   str = ""   # startup / mid / enterprise / holding

    # LLM-enriched intelligence
    executive_summary:      str = ""
    strategic_positioning:  str = ""
    professional_archetype: str = ""   # CIO / CDTO / CAIO / Transformation Executive / ...
    trajectory_markers:     list[str] = field(default_factory=list)
    strongest_assets:       list[str] = field(default_factory=list)
    weak_visibility_areas:  list[str] = field(default_factory=list)

    # Dashboard positioning levels
    ai_positioning_level:             PositioningLevel = PositioningLevel.LOW
    transformation_positioning_level: PositioningLevel = PositioningLevel.LOW
    executive_positioning_level:      PositioningLevel = PositioningLevel.LOW
    operational_depth_level:          PositioningLevel = PositioningLevel.LOW
    strategic_visibility_level:       PositioningLevel = PositioningLevel.LOW

    # Evidence references (maps signal → fragment from CV)
    evidence: dict[str, list[str]] = field(default_factory=dict)

    # Meta
    analysis_timestamp: datetime = field(default_factory=datetime.now)
    confidence_notes:   list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_resume(text: str, source_file: str = "", source_type: str = "text") -> ResumeProfile:
    """
    Entry point. Rule-based extraction followed by LLM enrichment.
    Gracefully degrades if LLM is unavailable.
    """
    cleaned = _normalize_text(text)
    profile = _extract_rule_based(cleaned, source_file, source_type)
    _enrich_with_llm(profile, cleaned)
    return profile


def load_resume(path: Path) -> tuple[str, str]:
    """
    Load resume text from file.
    Returns (text, source_type).
    Supports: .txt .md .docx .pdf
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace"), suffix.lstrip(".")

    if suffix == ".docx":
        return _from_docx(path), "docx"

    if suffix == ".pdf":
        return _from_pdf(path), "pdf"

    raise ValueError(f"Unsupported file type: {suffix}. Use .txt .md .docx .pdf")


# ---------------------------------------------------------------------------
# File adapters
# ---------------------------------------------------------------------------

def _from_docx(path: Path) -> str:
    try:
        import docx as _docx
        doc = _docx.Document(str(path))
        parts: list[str] = []
        for para in doc.paragraphs:
            if para.text.strip():
                parts.append(para.text)
        # Also extract tables
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append("  ".join(cells))
        return "\n".join(parts)
    except Exception as exc:
        raise ValueError(f"DOCX read error: {exc}") from exc


def _from_pdf(path: Path) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as exc:
        raise ValueError(f"PDF read error: {exc}") from exc


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\xa0", " ").replace("­", "").replace("​", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(ln.strip() for ln in text.splitlines()).strip()


# ---------------------------------------------------------------------------
# Rule-based extraction
# ---------------------------------------------------------------------------

# AI / ML signals
_AI_PATTERNS = [
    r"\bAI\b", r"\bML\b", r"\bLLM\b", r"\bGPT\b",
    r"machine learning", r"deep learning", r"нейросет",
    r"computer vision", r"\bNLP\b", r"MLOps", r"DataOps",
    r"AI governance", r"AI strategy", r"AI assistant",
    r"multi.?agent", r"predictive analytics", r"генеративн",
    r"decision intelligence", r"observabilit", r"автоматизац.*AI",
    r"ИИ\b", r"искусственн.*интеллект",
]

# Transformation signals
_TRANSFORM_PATTERNS = [
    r"цифров.*трансформац", r"digital transformation",
    r"цифровизац", r"digitali[sz]ation",
    r"change management", r"agile transformation",
    r"ERP.*внедр", r"внедр.*ERP",
    r"операционн.*трансформ", r"стратег.*трансформ",
    r"бизнес.трансформ",
]

# Governance signals
_GOVERNANCE_PATTERNS = [
    r"ITSM", r"ITIL", r"COBIT", r"ISO\s*\d{4,5}",
    r"кибербезопасност", r"information security",
    r"compliance", r"риск.*управлен", r"risk management",
    r"audit", r"SLA", r"governance",
    r"ИБ\b", r"безопасност.*данных",
]

# Technology domains
_TECH_PATTERNS = {
    "Cloud / DevOps":     [r"AWS", r"Azure", r"GCP", r"cloud", r"DevOps", r"Kubernetes", r"Docker"],
    "ERP / 1C":           [r"1С", r"1C\b", r"SAP\b", r"ERP", r"Oracle EBS"],
    "Data / Analytics":   [r"BI\b", r"DWH", r"data warehouse", r"аналитик", r"Power BI", r"Tableau", r"clickhouse"],
    "Infrastructure":     [r"инфраструктур", r"сеть", r"ITSM", r"datacenter", r"ЦОД"],
    "AI / ML":            [r"\bAI\b", r"\bML\b", r"machine learning", r"нейросет", r"LLM"],
    "Security":           [r"кибербезопасност", r"ИБ\b", r"SOC\b", r"SIEM", r"pentest"],
    "Architecture":       [r"архитектур", r"микросервис", r"API", r"интеграц"],
    "Process / BPMN":     [r"BPMN", r"процессн", r"автоматизац.*процесс"],
}

# Industries
_INDUSTRY_PATTERNS = {
    "Производство":  [r"производств", r"завод", r"фабрик", r"промышленност", r"manufacturing"],
    "Банки/Финансы": [r"банк", r"финанс", r"страхован", r"fintech", r"banking"],
    "Ритейл":        [r"ритейл", r"retail", r"торговл", r"e-commerce"],
    "Логистика":     [r"логистик", r"транспорт", r"склад", r"supply chain"],
    "ИТ-компания":   [r"ИТ.компани", r"software", r"разработк.*ПО", r"tech company"],
    "Телеком":       [r"телеком", r"telecom", r"связь\b", r"оператор\b"],
    "Госсектор":     [r"государствен", r"федеральн", r"министерств", r"госкорпорац"],
    "Консалтинг":    [r"консалтинг", r"consulting", r"advisory"],
    "Энергетика":    [r"энергетик", r"нефт", r"газ\b", r"energy"],
}

# Operational scope
_OPERATIONAL_PATTERNS = [r"команд.*\d+", r"\d+.*человек", r"бюджет.*\d", r"\d.*млн", r"\d.*млрд",
                          r"портфел.*проект", r"P&L", r"CAPEX", r"OPEX"]

# Business impact
_BUSINESS_PATTERNS = [r"ROI", r"снижен.*затрат", r"экономи.*\d", r"\d+%", r"рост.*выруч",
                       r"оптимизац.*процесс", r"KPI", r"SLA", r"measurable"]

# Innovation
_INNOVATION_PATTERNS = [r"инновац", r"R&D", r"стартап", r"MVP", r"пилот.*проект",
                         r"proof of concept", r"PoC", r"новое направлен"]

# Leadership scale heuristics
_COMPANY_SCALE = {
    "holding":    [r"холдинг", r"группа компаний", r"group of companies", r"\d{4,}.*сотрудник"],
    "enterprise": [r"\d{3,}.*сотрудник", r"крупн", r"федеральн", r"enterprise"],
    "mid":        [r"\d{2,3}.*сотрудник", r"средн"],
    "startup":    [r"стартап", r"startup"],
}


def _find_signals(patterns: list[str], text: str, max_evidence: int = 3) -> tuple[list[str], list[str]]:
    """
    Search patterns in text. Returns (unique_labels, evidence_fragments).
    label = normalized matched pattern key, evidence = surrounding text.
    """
    found_labels: list[str] = []
    evidence: list[str] = []
    lower = text.lower()
    for pat in patterns:
        for m in re.finditer(pat, lower, re.IGNORECASE):
            label = m.group(0).strip()
            if label and label not in found_labels:
                found_labels.append(label)
            if len(evidence) < max_evidence:
                start = max(0, m.start() - 40)
                end   = min(len(text), m.end() + 60)
                fragment = "…" + text[start:end].replace("\n", " ").strip() + "…"
                if fragment not in evidence:
                    evidence.append(fragment)
    return found_labels, evidence


def _estimate_years(text: str) -> int:
    """Estimate total career years from date ranges in CV text."""
    years: list[int] = []
    # Match 4-digit years: 2005–2024, 2005-present, 2005 — н.в.
    matches = re.findall(r"(19|20)(\d{2})", text)
    if matches:
        all_years = [int(f"{a}{b}") for a, b in matches]
        current = datetime.now().year
        all_years = [y for y in all_years if 1990 <= y <= current]
        if len(all_years) >= 2:
            return max(all_years) - min(all_years)
    return 0


def _detect_scale(text: str) -> tuple[str, str]:
    """Detect organizational_scale and leadership_scope."""
    lower = text.lower()

    # Organizational scale
    org_scale = "mid"
    for scale, patterns in _COMPANY_SCALE.items():
        for pat in patterns:
            if re.search(pat, lower, re.IGNORECASE):
                org_scale = scale
                break

    # Leadership scope
    scope = "individual"
    if re.search(r"директор|вице-президент|CIO|CTO|CDO|CDTO|CAIO|CPO|руководитель\s+\w+", lower, re.IGNORECASE):
        scope = "company"
    elif re.search(r"руководитель\s+отдел|начальник\s+отдел|head of|тимлид|lead", lower, re.IGNORECASE):
        scope = "team"
    elif re.search(r"руководитель\s+направлен|department head|division", lower, re.IGNORECASE):
        scope = "division"

    return org_scale, scope


def _rule_based_levels(profile: ResumeProfile) -> None:
    """Set positioning levels based on rule-based signal counts."""
    ai_count = len(profile.ai_signals)
    if ai_count >= 5:
        profile.ai_positioning_level = PositioningLevel.HIGH
    elif ai_count >= 2:
        profile.ai_positioning_level = PositioningLevel.MEDIUM
    else:
        profile.ai_positioning_level = PositioningLevel.LOW

    tf_count = len(profile.transformation_experience)
    if tf_count >= 4:
        profile.transformation_positioning_level = PositioningLevel.HIGH
    elif tf_count >= 2:
        profile.transformation_positioning_level = PositioningLevel.MEDIUM
    else:
        profile.transformation_positioning_level = PositioningLevel.LOW

    exec_signals = (
        profile.leadership_scope in ("company", "division")
        or profile.organizational_scale in ("enterprise", "holding")
    )
    profile.executive_positioning_level = PositioningLevel.HIGH if exec_signals else PositioningLevel.MEDIUM

    ops_count = len(profile.operational_scope)
    profile.operational_depth_level = (
        PositioningLevel.HIGH if ops_count >= 3
        else PositioningLevel.MEDIUM if ops_count >= 1
        else PositioningLevel.LOW
    )

    biz_count = len(profile.business_signals)
    profile.strategic_visibility_level = (
        PositioningLevel.HIGH if biz_count >= 4
        else PositioningLevel.MEDIUM if biz_count >= 2
        else PositioningLevel.LOW
    )


def _extract_rule_based(text: str, source_file: str, source_type: str) -> ResumeProfile:
    profile = ResumeProfile(raw_text=text, source_file=source_file, source_type=source_type)

    profile.years_experience = _estimate_years(text)
    profile.organizational_scale, profile.leadership_scope = _detect_scale(text)

    # AI signals
    ai_labels, ai_ev = _find_signals(_AI_PATTERNS, text)
    profile.ai_signals = ai_labels
    profile.evidence["ai_signals"] = ai_ev

    # Transformation
    tf_labels, tf_ev = _find_signals(_TRANSFORM_PATTERNS, text)
    profile.transformation_experience = tf_labels
    profile.evidence["transformation"] = tf_ev

    # Governance
    gov_labels, gov_ev = _find_signals(_GOVERNANCE_PATTERNS, text)
    profile.governance_signals = gov_labels
    profile.evidence["governance"] = gov_ev

    # Technology domains
    domains: list[str] = []
    domain_ev: list[str] = []
    for domain, patterns in _TECH_PATTERNS.items():
        labels, ev = _find_signals(patterns, text, max_evidence=1)
        if labels:
            domains.append(domain)
            domain_ev.extend(ev[:1])
    profile.technology_domains = domains
    profile.evidence["technology_domains"] = domain_ev

    # Industries
    industries: list[str] = []
    for industry, patterns in _INDUSTRY_PATTERNS.items():
        labels, _ = _find_signals(patterns, text)
        if labels:
            industries.append(industry)
    profile.industries = industries

    # Operational scope
    ops_labels, ops_ev = _find_signals(_OPERATIONAL_PATTERNS, text)
    profile.operational_scope = ops_labels
    profile.evidence["operational_scope"] = ops_ev

    # Business / impact signals
    biz_labels, biz_ev = _find_signals(_BUSINESS_PATTERNS, text)
    profile.business_signals = biz_labels
    profile.evidence["business_signals"] = biz_ev

    # Innovation
    inn_labels, _ = _find_signals(_INNOVATION_PATTERNS, text)
    profile.innovation_signals = inn_labels

    _rule_based_levels(profile)
    return profile


# ---------------------------------------------------------------------------
# LLM enrichment
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Ты — эксперт по executive career intelligence и resume analysis для топ-менеджеров уровня CIO/CTO/CDTO/CAIO.
Анализируешь резюме и строишь структурированный intelligence profile.
Отвечай строго в формате JSON без лишнего текста. Все строковые значения — на русском языке."""

_LLM_TEMPLATE = """\
Резюме:
---
{resume_text}
---

Контекст rule-based анализа:
- AI signals обнаружено: {ai_count}
- Трансформационный опыт: {tf_count} сигналов
- Технологические домены: {domains}
- Отрасли: {industries}
- Стаж: ~{years} лет
- Leadership scope: {scope}

Верни ТОЛЬКО валидный JSON (без markdown):
{{
  "executive_summary": "2-3 предложения: кто этот человек профессионально, ключевой expertise, уровень",
  "strategic_positioning": "1 предложение executive positioning statement для LinkedIn/резюме",
  "professional_archetype": "CIO|CDTO|CAIO|Transformation Executive|Operations Executive|Consulting Leader|AI Transformation Leader",
  "trajectory_markers": ["marker1", "marker2", "marker3"],
  "strongest_assets": ["asset1", "asset2", "asset3", "asset4", "asset5"],
  "weak_visibility_areas": ["area1", "area2", "area3"],
  "ai_positioning_level": "LOW|MEDIUM|HIGH",
  "transformation_positioning_level": "LOW|MEDIUM|HIGH",
  "executive_positioning_level": "LOW|MEDIUM|HIGH",
  "operational_depth_level": "LOW|MEDIUM|HIGH",
  "strategic_visibility_level": "LOW|MEDIUM|HIGH"
}}

Логика positioning levels:
- HIGH: явно выражено, много конкретных примеров с результатами
- MEDIUM: присутствует, но не акцентировано
- LOW: слабо видно или отсутствует

trajectory_markers — 3-5 конкретных карьерных траекторий:
CIO / CDTO / CAIO / AI Transformation Executive / Enterprise Architecture / Digital Operations / Consulting

strongest_assets — топ-5 реальных strengths с опорой на конкретный опыт из CV

weak_visibility_areas — что ЕСТЬ в опыте, но ПЛОХО видно в CV:
примеры: "AI governance hidden behind operational tasks",
"Transformation scope understated — delivery language dominates",
"Strategic ownership weakly visible despite C-level responsibilities"
"""


def _enrich_with_llm(profile: ResumeProfile, text: str) -> None:
    """Fill LLM-powered fields. Silently degrades on any error."""
    api_key = _get_api_key()
    if not api_key:
        _fill_fallback(profile)
        return

    try:
        prompt = _LLM_TEMPLATE.format(
            resume_text=text[:4000],
            ai_count=len(profile.ai_signals),
            tf_count=len(profile.transformation_experience),
            domains=", ".join(profile.technology_domains[:6]) or "—",
            industries=", ".join(profile.industries[:4]) or "—",
            years=profile.years_experience,
            scope=profile.leadership_scope,
        )

        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1800,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[: raw.rfind("```")].rstrip()
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        data = json.loads(raw)
        _apply_llm(profile, data)

    except Exception:
        _fill_fallback(profile)


def _apply_llm(profile: ResumeProfile, data: dict[str, Any]) -> None:
    profile.executive_summary     = data.get("executive_summary", "")
    profile.strategic_positioning = data.get("strategic_positioning", "")
    profile.professional_archetype = data.get("professional_archetype", "")
    profile.trajectory_markers    = data.get("trajectory_markers") or []
    profile.strongest_assets      = data.get("strongest_assets") or []
    profile.weak_visibility_areas = data.get("weak_visibility_areas") or []

    def _level(key: str) -> PositioningLevel:
        raw = data.get(key, "")
        return PositioningLevel(raw) if raw in PositioningLevel._value2member_map_ else PositioningLevel.MEDIUM

    profile.ai_positioning_level             = _level("ai_positioning_level")
    profile.transformation_positioning_level = _level("transformation_positioning_level")
    profile.executive_positioning_level      = _level("executive_positioning_level")
    profile.operational_depth_level          = _level("operational_depth_level")
    profile.strategic_visibility_level       = _level("strategic_visibility_level")


def _fill_fallback(profile: ResumeProfile) -> None:
    """Rule-based fallback when LLM is unavailable."""
    domains = ", ".join(profile.technology_domains[:3]) or "ИТ-управление"
    years = profile.years_experience

    profile.executive_summary = (
        f"Опытный ИТ-руководитель с ~{years}-летним стажем"
        f" в областях: {domains}. "
        "Детальный semantic analysis требует подключения LLM."
    )
    profile.strategic_positioning = (
        f"Executive IT leader с опытом в {domains}."
    )
    profile.professional_archetype = "CIO"
    if not profile.trajectory_markers:
        profile.trajectory_markers = ["CIO", "ИТ-директор", "Digital Leader"]
    if not profile.strongest_assets:
        profile.strongest_assets = [
            f"Опыт в {d}" for d in profile.technology_domains[:5]
        ] or ["ИТ-управление"]
    if not profile.weak_visibility_areas:
        profile.weak_visibility_areas = ["Требуется LLM для анализа narrative gaps"]
    profile.confidence_notes.append("LLM недоступен — использован rule-based fallback")


def _get_api_key() -> str:
    """Load API key from .env or environment."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key and not key.startswith("sk-ant-ВАШ"):
        return key
    return ""
