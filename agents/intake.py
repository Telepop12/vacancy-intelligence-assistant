"""
Intake & Vacancy Normalization Layer.

Unified ingestion pipeline for vacancies from multiple sources.
The analysis layer must never receive raw text directly — all input passes
through this module and arrives as a normalized VacancyInput.

Supported source types:
  text  — raw text string (CLI stdin or manual paste)
  file  — .txt / .md / .json file path
  html  — raw HTML string (web parser output)
  json  — structured dict from an API or parser
  url   — stub for future Playwright/requests integration

Future parser integrations (architecture-ready):
  hh.ru parser, LinkedIn parser, Telegram ingestion,
  Gmail parsing, Google Docs import, external APIs.
  Add a new adapter function and a SourceType entry — analysis layer unchanged.
"""
from __future__ import annotations

import html as _html_lib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SourceType(str, Enum):
    TEXT = "text"
    FILE = "file"
    URL  = "url"
    HTML = "html"
    JSON = "json"


class IntakeConfidence(str, Enum):
    HIGH   = "HIGH"
    MEDIUM = "MEDIUM"
    LOW    = "LOW"


# ---------------------------------------------------------------------------
# Unified vacancy schema
# ---------------------------------------------------------------------------

@dataclass
class VacancyInput:
    """
    Single source of truth for all downstream analysis layers.

    normalized_text is always the clean input for the analyzer.
    raw_text preserves the original for debugging and audit.
    """
    source_type:         SourceType
    source_name:         str
    raw_text:            str
    normalized_text:     str
    title:               str = ""
    company:             str = ""
    location:            str = ""
    salary:              str = ""
    url:                 str = ""
    detected_language:   str = ""
    ingestion_timestamp: datetime = field(default_factory=datetime.now)
    metadata:            dict[str, Any] = field(default_factory=dict)
    intake_confidence:   IntakeConfidence = IntakeConfidence.HIGH
    confidence_notes:    list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public adapters
# ---------------------------------------------------------------------------

def from_text(text: str, source_name: str = "text") -> VacancyInput:
    """Create VacancyInput from a raw text string."""
    normalized = _normalize(text)
    meta = _extract_metadata(normalized)
    notes: list[str] = []
    confidence = _assess_confidence(normalized, meta, notes)
    return VacancyInput(
        source_type=SourceType.TEXT,
        source_name=source_name,
        raw_text=text,
        normalized_text=normalized,
        title=meta.get("title", ""),
        company=meta.get("company", ""),
        location=meta.get("location", ""),
        salary=meta.get("salary", ""),
        detected_language=_detect_language(normalized),
        intake_confidence=confidence,
        confidence_notes=notes,
        metadata=meta,
    )


def from_file(path: Path) -> VacancyInput:
    """Create VacancyInput from a .txt, .md, or .json file."""
    path = Path(path)
    if not path.exists():
        return _error_input(SourceType.FILE, str(path), f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix not in {".txt", ".md", ".json"}:
        return _error_input(
            SourceType.FILE, path.name,
            f"Unsupported file type: {suffix}. Supported: .txt .md .json",
        )

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return _error_input(SourceType.FILE, path.name, f"Read error: {exc}")

    if suffix == ".json":
        vi = from_json(raw, source_name=path.name)
    else:
        vi = from_text(raw, source_name=path.name)
        vi.source_type = SourceType.FILE
    return vi


def from_html(html_text: str, url: str = "", source_name: str = "html") -> VacancyInput:
    """Create VacancyInput from raw HTML string."""
    try:
        extracted = _strip_html(html_text)
    except Exception as exc:
        return _error_input(SourceType.HTML, source_name, f"HTML parse error: {exc}")

    vi = from_text(extracted, source_name=source_name)
    vi.source_type = SourceType.HTML
    vi.url = url
    vi.raw_text = html_text
    return vi


def from_json(data: str | dict, source_name: str = "json") -> VacancyInput:
    """
    Create VacancyInput from a JSON string or dict.

    Understands common field names: description, text, body, vacancy_text,
    title, company, employer, location, area, salary, url, alternate_url.
    Compatible with hh.ru API response structure.
    """
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            return _error_input(SourceType.JSON, source_name, f"Invalid JSON: {exc}")
    else:
        parsed = dict(data)

    # Extract text from known field names
    text_fields = ["description", "text", "body", "vacancy_text", "content"]
    raw_body = ""
    for key in text_fields:
        val = parsed.get(key)
        if val and isinstance(val, str):
            raw_body = val
            break

    # Fallback: join all top-level string values
    if not raw_body:
        raw_body = "\n".join(str(v) for v in parsed.values() if isinstance(v, str) and len(str(v)) > 10)

    vi = from_text(raw_body, source_name=source_name)
    vi.source_type = SourceType.JSON
    vi.raw_text = json.dumps(parsed, ensure_ascii=False, indent=2)

    # Override metadata from explicit JSON fields (take priority over heuristics)
    # hh.ru отдаёт названия с HTML-сущностями (&quot;Компания&quot;) — раскодируем,
    # иначе шаблон (autoescape) покажет их буквально
    vi.title    = _html_lib.unescape(str(parsed.get("title") or parsed.get("name") or vi.title))
    vi.company  = _html_lib.unescape(str(parsed.get("company") or parsed.get("employer") or vi.company))
    vi.location = _html_lib.unescape(str(parsed.get("location") or parsed.get("area") or vi.location))
    # Явное поле salary важнее эвристики по тексту: hh отдаёт dict, письма и
    # сайты — строку. При None (на hh зарплата не указана) остаётся строгая
    # эвристика по описанию — иногда сумму пишут прямо в тексте.
    sal = parsed.get("salary")
    if isinstance(sal, dict):
        vi.salary = _parse_json_salary(parsed)
    elif isinstance(sal, str) and sal.strip():
        vi.salary = _html_lib.unescape(sal.strip())
    vi.url      = str(parsed.get("url") or parsed.get("alternate_url") or vi.url)
    vi.metadata.update({k: v for k, v in parsed.items() if not isinstance(v, (dict, list))})
    return vi


def from_url(url: str) -> VacancyInput:
    """
    Create VacancyInput from a vacancy URL.

    hh.ru vacancy links go through the official API (structured JSON,
    HIGH-quality metadata). Any other URL falls back to a generic HTML
    fetch — best effort, confidence is capped at MEDIUM because page
    chrome (menus, footers) pollutes the extracted text.
    """
    from agents import hh_api

    url = url.strip()
    if not re.match(r"https?://", url, re.IGNORECASE):
        url = "https://" + url

    hh_id = hh_api.extract_vacancy_id(url)
    if hh_id:
        try:
            data = hh_api.fetch_vacancy_data(hh_id)
        except hh_api.HHApiError as exc:
            return _error_input(SourceType.URL, url, str(exc))
        vi = from_json(data, source_name=f"hh.ru:{hh_id}")
        vi.source_type = SourceType.URL
        vi.url = vi.url or url
        if data.get("archived"):
            vi.confidence_notes.append("Вакансия в архиве hh.ru — вероятно, уже закрыта")
        return vi

    # Generic URL: plain HTML fetch (no JS rendering)
    try:
        html_text = _fetch_url(url)
    except Exception as exc:
        return _error_input(SourceType.URL, url, f"Не удалось загрузить страницу: {exc}")

    vi = from_html(html_text, url=url, source_name=url)
    vi.source_type = SourceType.URL
    if vi.intake_confidence == IntakeConfidence.HIGH:
        vi.intake_confidence = IntakeConfidence.MEDIUM
    vi.confidence_notes.append(
        "Универсальный парсинг HTML — текст может содержать элементы страницы"
    )
    return vi


def _fetch_url(url: str, timeout: int = 20) -> str:
    """Fetch raw HTML from an arbitrary URL (no JS rendering)."""
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
            "Accept-Language": "ru,en;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


# ---------------------------------------------------------------------------
# Normalization pipeline
# ---------------------------------------------------------------------------

_HTML_BLOCK_RE = re.compile(r"<(?:p|br|li|ul|ol|div|h[1-6]|tr)\b[^>]*>", re.IGNORECASE)


def _normalize(text: str) -> str:
    """Return clean text suitable for the analysis layer."""
    # Unicode NFC
    text = unicodedata.normalize("NFC", text)
    # Unescape HTML entities (&nbsp; &amp; etc.)
    text = _html_lib.unescape(text)
    # Описания hh приходят с <p>/<ul>/<li>: блочные теги → переводы строк,
    # иначе соседние пункты склеиваются и эвристики читают «зарплата» +
    # следующий пункт как сумму
    if _HTML_BLOCK_RE.search(text):
        text = _strip_html(text)
    # Remove residual HTML tags
    text = re.sub(r"<[^>]{0,300}>", " ", text)
    # Strip invisible / zero-width chars
    text = text.replace("­", "")   # soft hyphen
    text = text.replace("​", "")   # zero-width space
    text = text.replace("‌", "")   # zero-width non-joiner
    text = text.replace("\xa0", " ")    # non-breaking space
    # Collapse horizontal whitespace
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ consecutive blank lines → double newline
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip each line; drop lines that are pure decoration
    lines = []
    for ln in text.splitlines():
        ln = ln.strip()
        if re.fullmatch(r"[-–—=*_•·.▪▸►◾◽]{2,}", ln):
            continue  # decoration line
        lines.append(ln)
    return "\n".join(lines).strip()


class _TagStripper(HTMLParser):
    """Extracts readable text from HTML, inserting newlines at block elements."""

    _SKIP  = {"script", "style", "head", "meta", "link", "noscript", "svg", "img"}
    _BLOCK = {
        "p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
        "tr", "td", "th", "section", "article", "header", "footer", "ul", "ol",
    }

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _strip_html(html_text: str) -> str:
    stripper = _TagStripper()
    stripper.feed(html_text)
    return stripper.get_text()


# ---------------------------------------------------------------------------
# Metadata extraction (heuristic)
# ---------------------------------------------------------------------------

_TITLE_RE = [
    r"(?:вакансия|должность|позиция|роль)[:\s]+([^\n]{5,80})",
    r"(?:vacancy|position|role|job\s+title)[:\s]+([^\n]{5,80})",
]
_COMPANY_RE = [
    r"(?:компания|работодатель|организация|о\s+компании)[:\s]+([^\n]{3,80})",
    r"(?:company|employer)[:\s]+([^\n]{3,80})",
]
_LOCATION_RE = [
    r"(?:локация|город|местоположение|офис|адрес)[:\s]+([^\n]{3,60})",
    r"(?:location|city|office)[:\s]+([^\n]{3,60})",
    r"\b(Москва|Санкт-Петербург|Новосибирск|Екатеринбург|Казань|Краснодар|Нижний\s+Новгород)\b",
]
_SALARY_RE = [
    # После ключевого слова нужен разделитель или сумма — иначе «Конкурентная
    # зарплата» + следующий пункт условий превращались в «зарплату».
    # «Компенсация» в русских вакансиях — это перки (питание, связь), не оклад.
    r"(?:зарплата|заработная плата|з/п|оклад|доход)\s*[:—–-]\s*([^\n]{3,60})",
    r"(?:зарплата|заработная плата|з/п|оклад|доход)\s+((?:от|до)\s*\d[^\n]{0,55}|\d[^\n]{2,55})",
    r"(?:salary|compensation)\s*[:—–-]\s*([^\n]{3,60})",
    r"(?:salary|compensation)\s+((?:from|up\s+to)\s*\d[^\n]{0,55})",
    # Голая сумма — только с валютой: «300 тыс. ₽», «400 000 рублей», «150 000 р.»;
    # без валюты «300 тыс. кв м», «700 тыс. клиентов», «146к2» — не зарплата,
    # как и «500 рублей в день» (компенсация питания).
    r"(\d{2,}[\d\s–-]*(?:тыс\.?\s*)?(?:руб(?:лей|\.)?|₽|р\.)(?![а-яa-z0-9])"
    r"(?!\s*(?:в\s+день|в\s+час|за\s+час|за\s+день|от\s+стоимости))[^\n]{0,30})",
]


def _first_match(patterns: list[str], text: str) -> str:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return (m.group(1) if m.lastindex else m.group(0)).strip()
    return ""


def _extract_metadata(text: str) -> dict[str, str]:
    title = _first_match(_TITLE_RE, text)
    if not title:
        # Fallback: first non-empty line of reasonable length
        for line in text.splitlines():
            line = line.strip()
            if 5 <= len(line) <= 120 and not line.endswith(":"):
                title = line
                break
    return {
        "title":    title,
        "company":  _first_match(_COMPANY_RE, text),
        "location": _first_match(_LOCATION_RE, text),
        "salary":   _first_match(_SALARY_RE, text),
    }


def _parse_json_salary(data: dict) -> str:
    """Parse hh.ru-style salary dict → human-readable string."""
    sal = data.get("salary")
    if not sal or not isinstance(sal, dict):
        return ""
    parts = []
    if sal.get("from"):
        parts.append(f"от {sal['from']}")
    if sal.get("to"):
        parts.append(f"до {sal['to']}")
    currency = sal.get("currency", "")
    return " ".join(parts) + (f" {currency}" if currency else "")


# ---------------------------------------------------------------------------
# Language detection (simple heuristic)
# ---------------------------------------------------------------------------

def _detect_language(text: str) -> str:
    ru = len(re.findall(r"[а-яёА-ЯЁ]", text))
    en = len(re.findall(r"[a-zA-Z]", text))
    if ru > en * 1.5:
        return "ru"
    if en > ru * 1.5:
        return "en"
    return "mixed" if (ru + en) > 0 else "unknown"


# ---------------------------------------------------------------------------
# Confidence assessment
# ---------------------------------------------------------------------------

_MIN_HIGH   = 300   # chars
_MIN_MEDIUM = 100


def _assess_confidence(
    text: str,
    meta: dict[str, str],
    notes: list[str],
) -> IntakeConfidence:
    issues = 0

    if len(text) < _MIN_MEDIUM:
        notes.append(f"Text too short ({len(text)} chars)")
        issues += 2
    elif len(text) < _MIN_HIGH:
        notes.append(f"Short text ({len(text)} chars) — may be incomplete")
        issues += 1

    if not meta.get("title"):
        notes.append("Job title not detected")
        issues += 1

    if not meta.get("company"):
        notes.append("Company name not detected")

    has_sections = any(
        kw in text.lower()
        for kw in ["обязанности", "требования", "условия", "задачи",
                   "responsibilities", "requirements", "conditions", "qualifications"]
    )
    if not has_sections:
        notes.append("No standard vacancy sections detected")
        issues += 1

    if issues >= 3:
        return IntakeConfidence.LOW
    if issues >= 1:
        return IntakeConfidence.MEDIUM
    return IntakeConfidence.HIGH


# ---------------------------------------------------------------------------
# Error helper
# ---------------------------------------------------------------------------

def _error_input(
    source_type: SourceType,
    source_name: str,
    message: str,
    confidence: IntakeConfidence = IntakeConfidence.LOW,
) -> VacancyInput:
    return VacancyInput(
        source_type=source_type,
        source_name=source_name,
        raw_text="",
        normalized_text="",
        intake_confidence=confidence,
        confidence_notes=[message],
        metadata={"error": message},
    )
