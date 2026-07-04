"""
hh.ru integration — dual-channel, stdlib-only (urllib).

Channel 1 (preferred): official API with an application token.
  In December 2025 hh.ru closed anonymous access to /vacancies (HTTP 403).
  If HH_ACCESS_TOKEN is set in the environment (.env), requests go to
  api.hh.ru with a Bearer header. Register an app at https://dev.hh.ru
  to obtain one.

Channel 2 (fallback, no auth): public HTML pages.
  Vacancy pages embed a JSON-LD JobPosting block (title, employer,
  full description, location) and are served without JavaScript.
  Search result pages contain vacancy ids extractable by regex.
  Fetching is throttled to stay polite; volume is personal-use scale.

Both channels normalize to the same flat dict shape consumed by
agents.intake.from_json().
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

HH_API_BASE = "https://api.hh.ru"
HH_SITE_BASE = "https://hh.ru"

_API_USER_AGENT = "VacancyIntelligenceAssistant/1.0 (personal job-search tool)"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_REQUEST_DELAY = 0.6   # seconds between batch page fetches
_TIMEOUT = 25          # seconds

# hh.ru and its regional mirrors publish the same vacancy ids
_VACANCY_URL_RE = re.compile(
    r"(?:hh\.ru|hh\.kz|hh\.uz|headhunter\.ge|rabota\.by)/vacancy/(\d+)", re.IGNORECASE
)
_JSONLD_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)
_SEARCH_ID_RE = re.compile(r"/vacancy/(\d{6,})")


class HHApiError(Exception):
    """hh.ru request failed (network, HTTP error, or unparseable payload)."""


def extract_vacancy_id(url: str) -> str | None:
    """Return the vacancy id from an hh.ru vacancy URL, or None if not one."""
    m = _VACANCY_URL_RE.search(url)
    return m.group(1) if m else None


def _token() -> str:
    return os.environ.get("HH_ACCESS_TOKEN", "").strip()


# ---------------------------------------------------------------------------
# Low-level fetch helpers
# ---------------------------------------------------------------------------

def _get_json(path: str, params: dict[str, Any] | None = None) -> dict:
    """GET api.hh.ru path with the application token."""
    url = HH_API_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    headers = {"User-Agent": _API_USER_AGENT}
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HHApiError(f"hh.ru API вернул HTTP {exc.code} для {path}") from exc
    except urllib.error.URLError as exc:
        raise HHApiError(f"Сетевая ошибка при обращении к api.hh.ru: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HHApiError(f"Некорректный ответ hh.ru API: {exc}") from exc


def _get_html(url: str) -> str:
    """GET a public hh.ru page as a regular browser would."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _BROWSER_USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise HHApiError(f"hh.ru вернул HTTP {exc.code} для {url}") from exc
    except urllib.error.URLError as exc:
        raise HHApiError(f"Сетевая ошибка при обращении к hh.ru: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Normalization to the intake dict shape
# ---------------------------------------------------------------------------

def _api_record_to_intake(data: dict) -> dict:
    """Flatten a full API vacancy record (employer/area are nested dicts)."""
    employer = (data.get("employer") or {}).get("name", "")
    area = (data.get("area") or {}).get("name", "")
    name = data.get("name", "")

    sections: list[str] = []
    if name:
        sections.append(f"Вакансия: {name}")
    if employer:
        sections.append(f"Компания: {employer}")
    if area:
        sections.append(f"Город: {area}")
    exp = (data.get("experience") or {}).get("name", "")
    if exp:
        sections.append(f"Требуемый опыт: {exp}")
    employment = (data.get("employment") or {}).get("name", "")
    schedule = (data.get("schedule") or {}).get("name", "")
    if employment or schedule:
        sections.append("Занятость: " + " · ".join(s for s in (employment, schedule) if s))
    sections.append(data.get("description") or "")
    skills = [s.get("name", "") for s in data.get("key_skills") or [] if s.get("name")]
    if skills:
        sections.append("Ключевые навыки: " + ", ".join(skills))

    return {
        "name": name,
        "employer": employer,
        "area": area,
        "salary": data.get("salary"),
        "alternate_url": data.get("alternate_url", ""),
        "published_at": data.get("published_at", ""),
        "hh_id": str(data.get("id", "")),
        "archived": bool(data.get("archived", False)),
        "description": "\n\n".join(s for s in sections if s),
    }


def _jsonld_to_intake(data: dict, vacancy_id: str) -> dict:
    """Flatten a JSON-LD JobPosting block from a public vacancy page."""
    org = (data.get("hiringOrganization") or {}).get("name", "")
    address = ((data.get("jobLocation") or {}).get("address") or {})
    area = address.get("addressLocality", "") or address.get("addressRegion", "")
    name = data.get("title", "")

    salary = None
    base = data.get("baseSalary") or {}
    value = base.get("value") or {}
    if value.get("minValue") or value.get("maxValue"):
        salary = {
            "from": value.get("minValue"),
            "to": value.get("maxValue"),
            "currency": base.get("currency", ""),
        }

    sections: list[str] = []
    if name:
        sections.append(f"Вакансия: {name}")
    if org:
        sections.append(f"Компания: {org}")
    if area:
        sections.append(f"Город: {area}")
    exp = data.get("experienceRequirements", "")
    if isinstance(exp, dict):
        exp = exp.get("description", "") or ""
    if exp:
        sections.append(f"Требуемый опыт: {exp}")
    employment = data.get("employmentType", "")
    if employment:
        sections.append(f"Занятость: {employment}")
    sections.append(data.get("description") or "")

    return {
        "name": name,
        "employer": org,
        "area": area,
        "salary": salary,
        "alternate_url": f"{HH_SITE_BASE}/vacancy/{vacancy_id}",
        "published_at": data.get("datePosted", ""),
        "hh_id": vacancy_id,
        "archived": False,
        "description": "\n\n".join(s for s in sections if s),
    }


# ---------------------------------------------------------------------------
# Public: single vacancy
# ---------------------------------------------------------------------------

def fetch_vacancy_data(vacancy_id: str) -> dict:
    """
    Fetch one vacancy as a flat intake dict.
    API channel when a token is configured, HTML/JSON-LD otherwise.
    """
    if _token():
        try:
            return _api_record_to_intake(_get_json(f"/vacancies/{vacancy_id}"))
        except HHApiError:
            pass  # token expired/insufficient — fall through to HTML

    html = _get_html(f"{HH_SITE_BASE}/vacancy/{vacancy_id}")
    for block in _JSONLD_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if data.get("@type") == "JobPosting":
            return _jsonld_to_intake(data, vacancy_id)
    raise HHApiError(
        f"Страница вакансии {vacancy_id} не содержит данных JobPosting — "
        "возможно, вакансия в архиве или hh.ru показал проверку на робота"
    )


# ---------------------------------------------------------------------------
# Public: search
# ---------------------------------------------------------------------------

def search_vacancy_ids(
    text: str,
    area: str | int | None = 113,
    max_pages: int = 1,
    search_field: str = "name",
    extra_params: dict[str, Any] | None = None,
) -> list[str]:
    """
    Return vacancy ids matching a search query, in page order.

    search_field="name" limits matching to the vacancy title — for C-level
    queries this cuts noise dramatically (a body-text match on "CIO" is
    usually a mention, not the role).
    """
    if _token():
        try:
            return _search_ids_api(text, area, max_pages, search_field, extra_params)
        except HHApiError:
            pass  # fall through to HTML search

    return _search_ids_html(text, area, max_pages, search_field)


def _search_ids_api(text, area, max_pages, search_field, extra_params) -> list[str]:
    ids: list[str] = []
    for page in range(max_pages):
        params: dict[str, Any] = {
            "text": text, "per_page": 50, "page": page, "search_field": search_field,
        }
        if area:
            params["area"] = area
        if extra_params:
            params.update(extra_params)
        resp = _get_json("/vacancies", params)
        ids.extend(str(item["id"]) for item in resp.get("items", []) if item.get("id"))
        if page >= resp.get("pages", 1) - 1:
            break
        time.sleep(_REQUEST_DELAY)
    return ids


def _search_ids_html(text, area, max_pages, search_field) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for page in range(max_pages):
        params = {"text": text, "search_field": search_field, "page": page}
        if area:
            params["area"] = area
        url = f"{HH_SITE_BASE}/search/vacancy?" + urllib.parse.urlencode(params)
        html = _get_html(url)
        page_ids = [i for i in _SEARCH_ID_RE.findall(html) if i not in seen]
        if not page_ids:
            break
        for i in page_ids:
            seen.add(i)
            ids.append(i)
        time.sleep(_REQUEST_DELAY)
    return ids


def fetch_vacancies_batch(vacancy_ids: list[str]) -> tuple[dict[str, dict], dict[str, str]]:
    """
    Fetch full intake dicts for a list of ids, politely throttled.
    Returns (fetched: id → intake dict, errors: id → message).
    """
    fetched: dict[str, dict] = {}
    errors: dict[str, str] = {}
    for i, vid in enumerate(vacancy_ids):
        if i:
            time.sleep(_REQUEST_DELAY)
        try:
            fetched[vid] = fetch_vacancy_data(vid)
        except HHApiError as exc:
            errors[vid] = str(exc)
    return fetched, errors
