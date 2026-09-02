"""
Career Watch — обходчик карьерных страниц целевых работодателей.

Таргет-лист: config/target_companies.yaml (согласован заказчиком 02.09.2026).
Логика одного прогона для каждой компании:

  channel=site  страница(и) вакансий → ссылки на вакансии из HTML по
                link_pattern (+ встроенный JSON __NEXT_DATA__/__INITIAL_STATE__
                при json_scan, + JSON API при api_url)
  channel=hh    один поиск hh.ru по работодателю (employer_id + hh_query по
                названию) — для JS-сайтов и сайтов за антиботом
  → фильтр названий (title_include / title_exclude): в конвейер идут только
    C-level / ИТ-управление, а не 600 рабочих вакансий комбината
  → снапшот-дифф: output/career_watch/<company>.json хранит уже виденные
    ссылки; новые загружаются (страница вакансии → intake.from_html)
    и триажатся rule-based скорингом в общий search state с
    source="career:<Компания>" — дальше обычный конвейер (карточка,
    полный анализ, пакет отклика).

Без LLM: массовый обход не тратит бюджет (правило проекта). Три сайта
подписаны российским корневым CA — сертификат лежит в config/certs и
добавляется в SSL-контекст (проверено 02.09: job.alfabank.ru, team.rzd.ru).
Состояние прогона: output/career_watch_state.json.
"""
from __future__ import annotations

import hashlib
import html as _html_lib
import json
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "target_companies.yaml"
CERT_PATH = BASE_DIR / "config" / "certs" / "russian_trusted_root_ca.pem"
STATE_PATH = BASE_DIR / "output" / "career_watch_state.json"
SNAP_DIR = BASE_DIR / "output" / "career_watch"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_TIMEOUT = 40   # SSR-страницы на 1 МБ (МегаФон, Softline) отдаются медленно
_SITE_DELAY = (1.5, 3.0)      # пауза между запросами к одному сайту
_COMPANY_DELAY = (1.0, 2.5)   # пауза между компаниями

DEFAULT_CONFIG: dict = {
    # Сильные титулы проходят сами по себе; слабые (руководитель/начальник/
    # заместитель) — только вместе с ИТ/цифровым контекстом в названии,
    # иначе в триаж идут «Начальник отделения почтовой связи».
    "title_include": [r"\bcio\b", r"\bcto\b", r"\bcdo\b", r"\bcdto\b", "технический директор"],
    "title_include_weak": ["директор", "руководител", "начальник", "заместител", r"\bhead\b", r"\bchief\b"],
    "title_context": [r"\bит\b", r"\bit\b", "информац", "цифров", "digital", "технолог",
                      "данн", r"\bdata\b", "разработ", "инфраструктур", "автоматиз"],
    "title_exclude": ["стаж[её]р", "продаж"],
    "hh_query_default": "директор OR руководитель OR CIO OR CTO OR CDTO",
    "max_new_per_company": 10,
    "max_hh_companies_per_run": 8,
    "companies": [],
}


class CareerFetchError(Exception):
    pass


# ---------------------------------------------------------------------------
# Конфиг
# ---------------------------------------------------------------------------

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            user_cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            cfg.update({k: v for k, v in user_cfg.items() if v is not None})
        except yaml.YAMLError:
            pass
    return cfg


def _compile(patterns: list[str]) -> list[re.Pattern]:
    out = []
    for p in patterns or []:
        try:
            out.append(re.compile(p, re.IGNORECASE))
        except re.error:
            continue
    return out


def title_matches(title: str, include: list[re.Pattern], exclude: list[re.Pattern],
                  weak: list[re.Pattern] | None = None,
                  context: list[re.Pattern] | None = None) -> bool:
    """Сильный титул — сам по себе; слабый — только с ИТ/цифровым контекстом."""
    t = (title or "").strip()
    if len(t) < 4:
        return False
    if any(rx.search(t) for rx in exclude):
        return False
    if any(rx.search(t) for rx in include):
        return True
    if weak and context and any(rx.search(t) for rx in weak):
        return any(rx.search(t) for rx in context)
    return False


class TitleFilter:
    """Скомпилированный фильтр названий из конфига."""

    def __init__(self, cfg: dict) -> None:
        self.include = _compile(cfg.get("title_include", []))
        self.exclude = _compile(cfg.get("title_exclude", []))
        self.weak = _compile(cfg.get("title_include_weak", []))
        self.context = _compile(cfg.get("title_context", []))

    def __call__(self, title: str) -> bool:
        return title_matches(title, self.include, self.exclude, self.weak, self.context)


# ---------------------------------------------------------------------------
# Загрузка страниц
# ---------------------------------------------------------------------------

_ssl_ctx: ssl.SSLContext | None = None


def _ssl_context() -> ssl.SSLContext:
    global _ssl_ctx
    if _ssl_ctx is None:
        ctx = ssl.create_default_context()
        if CERT_PATH.exists():
            try:
                ctx.load_verify_locations(str(CERT_PATH))
            except ssl.SSLError:
                pass
        _ssl_ctx = ctx
    return _ssl_ctx


def fetch(url: str, timeout: int = _TIMEOUT) -> str:
    """GET страницы как браузер; HTTP-ошибки и сеть → CareerFetchError."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise CareerFetchError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise CareerFetchError(f"сеть: {str(exc.reason)[:80]}") from exc
    except (TimeoutError, OSError) as exc:
        raise CareerFetchError(f"сеть: {str(exc)[:80]}") from exc


def _site_sleep() -> None:
    time.sleep(random.uniform(*_SITE_DELAY))


# ---------------------------------------------------------------------------
# Извлечение ссылок на вакансии
# ---------------------------------------------------------------------------

@dataclass
class VacancyLink:
    title: str
    url: str
    description: str = ""   # если текст пришёл сразу (JSON API)
    hh_id: str = ""         # канал hh


class _LinkCollector(HTMLParser):
    """Собирает <a href> с их видимым текстом."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._href = href
                self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            # Карточка вакансии — это <a> с вложенными блоками (название, город,
            # зарплата) без пробелов между ними. Название — первый содержательный
            # фрагмент; если он короткий (иконка, метка) — берём весь текст.
            chunks = [re.sub(r"\s+", " ", c).strip() for c in self._text]
            chunks = [c for c in chunks if c]
            text = chunks[0] if chunks and len(chunks[0]) >= 6 else " ".join(chunks)
            self.links.append((self._href, text))
            self._href = None
            self._text = []


def extract_links(html: str, base_url: str, link_pattern: str) -> list[VacancyLink]:
    """Ссылки страницы, чей путь подходит под link_pattern; текст = название."""
    rx = re.compile(link_pattern, re.IGNORECASE) if link_pattern else None
    parser = _LinkCollector()
    try:
        parser.feed(html)
    except Exception:
        return []
    out: dict[str, VacancyLink] = {}
    for href, text in parser.links:
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urllib.parse.urljoin(base_url, href)
        parts = urllib.parse.urlsplit(url)
        # Паттерн — по пути; для сайтов с id в параметрах — по пути с query
        if rx and not (rx.search(parts.path) or (parts.query and rx.search(parts.path + "?" + parts.query))):
            continue
        url = url.split("#", 1)[0]
        title = _html_lib.unescape(text)
        if url not in out or (title and not out[url].title):
            out[url] = VacancyLink(title=title, url=url)
    return list(out.values())


_TITLE_KEYS = ("title", "name", "vacancyName", "vacancy_name", "position")
_ID_KEYS = ("id", "vacancyId", "vacancy_id", "documentId", "slug", "code", "alias")
_URL_KEYS = ("url", "link", "href", "alternate_url", "canonicalUrl")
_DESC_KEYS = ("description", "details", "text", "responsibilities", "body")


def _walk_json(obj: Any, found: list[dict], depth: int = 0) -> None:
    if depth > 30:
        return
    if isinstance(obj, dict):
        title = next((obj[k] for k in _TITLE_KEYS if isinstance(obj.get(k), str)), None)
        has_id = any(k in obj for k in _ID_KEYS) or any(k in obj for k in _URL_KEYS)
        if title and has_id and 4 <= len(title) <= 160 and "\n" not in title:
            found.append(obj)
        for v in obj.values():
            _walk_json(v, found, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _walk_json(v, found, depth + 1)


def _json_item_to_link(item: dict, base_url: str, url_template: str = "") -> VacancyLink:
    title = _html_lib.unescape(next(item[k] for k in _TITLE_KEYS if isinstance(item.get(k), str)))
    url = next((item[k] for k in _URL_KEYS if isinstance(item.get(k), str) and item[k]), "")
    if url:
        url = urllib.parse.urljoin(base_url, url)
    elif url_template:
        try:
            url = url_template.format(**{k: item.get(k, "") for k in _ID_KEYS})
        except (KeyError, IndexError):
            url = ""
    if not url:
        ident = next((str(item[k]) for k in _ID_KEYS if item.get(k) not in (None, "")), "")
        url = f"{base_url}#{ident}" if ident else base_url
    desc = next((item[k] for k in _DESC_KEYS if isinstance(item.get(k), str)), "")
    if desc:
        desc = re.sub(r"<[^>]{0,300}>", " ", _html_lib.unescape(desc))
    return VacancyLink(title=title, url=url, description=desc)


_EMBEDDED_JSON_RES = (
    re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S),
    re.compile(r"__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*(?:</script>|window\.)", re.S),
    re.compile(r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', re.S),
)


def extract_json_vacancies(text: str, base_url: str, url_template: str = "") -> list[VacancyLink]:
    """Вакансии из JSON: ответ API целиком или блобы, встроенные в HTML."""
    blobs: list[Any] = []
    stripped = text.lstrip()
    if stripped[:1] in "[{":
        try:
            blobs.append(json.loads(stripped))
        except json.JSONDecodeError:
            pass
    if not blobs:
        for rx in _EMBEDDED_JSON_RES:
            for m in rx.finditer(text):
                try:
                    blobs.append(json.loads(m.group(1)))
                except json.JSONDecodeError:
                    continue
    found: list[dict] = []
    for blob in blobs:
        _walk_json(blob, found)
    out: dict[str, VacancyLink] = {}
    for item in found:
        link = _json_item_to_link(item, base_url, url_template)
        out.setdefault(link.url, link)
    return list(out.values())


# ---------------------------------------------------------------------------
# Снапшоты и состояние
# ---------------------------------------------------------------------------

def _snap_path(name: str) -> Path:
    safe = re.sub(r"[^\w\-]", "_", name)
    return SNAP_DIR / f"{safe}.json"


def load_snapshot(name: str) -> dict[str, dict]:
    p = _snap_path(name)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_snapshot(name: str, snap: dict[str, dict]) -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    _snap_path(name).write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_run": "", "companies": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def career_vid(url: str) -> str:
    """Стабильный id вакансии с карьерного сайта для vacancy_store/search state."""
    return "c" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Прогон
# ---------------------------------------------------------------------------

@dataclass
class CompanyRunResult:
    name: str
    channel: str
    found: int = 0        # ссылок/вакансий на странице (после дедупа)
    matched: int = 0      # прошли фильтр названий
    new: int = 0          # не было в снапшоте
    registered: int = 0   # загружены и затриажены
    skipped: int = 0      # новые сверх лимита — в следующий раз
    error: str = ""
    new_titles: list[str] = field(default_factory=list)


@dataclass
class WatchRunResult:
    companies: list[CompanyRunResult]
    new_total: int
    errors: list[str] = field(default_factory=list)


def _collect_site_links(company: dict) -> list[VacancyLink]:
    links: dict[str, VacancyLink] = {}
    template = company.get("json_url_template", "")
    first = True
    errors: list[str] = []
    for url in company.get("urls") or []:
        if not first:
            _site_sleep()
        first = False
        try:
            html = fetch(url)
        except CareerFetchError as exc:
            errors.append(f"{url}: {exc}")
            continue
        for link in extract_links(html, url, company.get("link_pattern", "")):
            links.setdefault(link.url, link)
        if company.get("json_scan"):
            for link in extract_json_vacancies(html, url, template):
                links.setdefault(link.url, link)
    if company.get("api_url"):
        if not first:
            _site_sleep()
        text = fetch(company["api_url"])
        base = company.get("site_url") or company["api_url"]
        for link in extract_json_vacancies(text, base, template):
            links.setdefault(link.url, link)
    if errors and not links:
        raise CareerFetchError("; ".join(errors))
    return list(links.values()), errors


def _register_site_vacancy(profile, company: dict, link: VacancyLink) -> None:
    from agents import hh_search, vacancy_store
    from agents.intake import from_html, from_text

    if link.description:
        vi = from_text(link.description, source_name=link.url)
    else:
        vi = from_html(fetch(link.url), url=link.url, source_name=link.url)
    vid = career_vid(link.url)
    data = {
        "name": link.title or vi.title,
        "employer": company["name"],
        "area": vi.location,
        "salary": None,
        "alternate_url": link.url,
        "published_at": datetime.now().strftime("%Y-%m-%d"),
        "hh_id": vid,
        "description": vi.normalized_text or link.title,
    }
    vacancy_store.save_vacancy(data, vid)
    hh_search.register_vacancy(profile, data, vid, source=f"career:{company['name']}")


def watch_site_company(company: dict, profile, cfg: dict, accept: TitleFilter) -> CompanyRunResult:
    res = CompanyRunResult(name=company["name"], channel="site")
    links, url_errors = _collect_site_links(company)
    if url_errors:
        res.error = "; ".join(url_errors)  # часть страниц не открылась — остальное обработано
    res.found = len(links)
    matched = [l for l in links if accept(l.title)]
    res.matched = len(matched)

    snap = load_snapshot(company["name"])
    now = datetime.now().isoformat(timespec="seconds")
    new_links = [l for l in matched if l.url not in snap]
    res.new = len(new_links)
    cap = int(cfg.get("max_new_per_company", 10))
    for i, link in enumerate(new_links):
        if i >= cap:
            res.skipped += 1
            continue  # снапшот не трогаем — подхватится в следующий раз
        try:
            if i and not link.description:
                _site_sleep()
            _register_site_vacancy(profile, company, link)
            snap[link.url] = {"title": link.title, "first_seen": now, "last_seen": now,
                              "vid": career_vid(link.url)}
            res.registered += 1
            res.new_titles.append(link.title)
        except CareerFetchError as exc:
            res.error = f"вакансия {link.url}: {exc}"  # остаётся новой — повтор в следующий раз
    for link in matched:
        if link.url in snap:
            snap[link.url]["last_seen"] = now
    save_snapshot(company["name"], snap)
    return res


def watch_hh_company(company: dict, profile, cfg: dict, accept: TitleFilter) -> CompanyRunResult:
    from agents import hh_api, hh_search, vacancy_store

    res = CompanyRunResult(name=company["name"], channel="hh")
    query = company.get("hh_query") or cfg.get("hh_query_default", "")
    ids = hh_api.search_vacancy_ids(
        query, area=None, max_pages=1, search_field="name",
        extra_params={"employer_id": company["hh_employer_id"], "ord_by": "publication_time"},
    )
    res.found = len(ids)
    snap = load_snapshot(company["name"])
    now = datetime.now().isoformat(timespec="seconds")
    new_ids = [i for i in ids if f"{hh_api.HH_SITE_BASE}/vacancy/{i}" not in snap]
    res.new = len(new_ids)
    cap = int(cfg.get("max_new_per_company", 10))
    to_fetch, res.skipped = new_ids[:cap], max(0, len(new_ids) - cap)

    # Уже известные общему триажу (автопоиск / радар) не перезагружаем
    fresh = []
    for vid in to_fetch:
        rec = hh_search.get_state_item(vid)
        if rec:
            url = f"{hh_api.HH_SITE_BASE}/vacancy/{vid}"
            snap[url] = {"title": rec.get("title", ""), "first_seen": now, "last_seen": now, "vid": vid}
            if accept(rec.get("title", "")):
                res.matched += 1
        else:
            fresh.append(vid)

    fetched, errors, rate_limited = hh_api.fetch_vacancies_batch(fresh) if fresh else ({}, {}, False)
    for vid, data in fetched.items():
        url = f"{hh_api.HH_SITE_BASE}/vacancy/{vid}"
        snap[url] = {"title": data.get("name", ""), "first_seen": now, "last_seen": now, "vid": vid}
        if not accept(data.get("name", "")):
            continue
        res.matched += 1
        vacancy_store.save_vacancy(data, vid)
        hh_search.register_vacancy(profile, data, vid, source=f"career:{company['name']}")
        res.registered += 1
        res.new_titles.append(data.get("name", ""))
    if errors:
        res.error = f"hh: не загружено {len(errors)}" + (" (rate limit)" if rate_limited else "")
    for vid in ids:
        url = f"{hh_api.HH_SITE_BASE}/vacancy/{vid}"
        if url in snap:
            snap[url]["last_seen"] = now
    save_snapshot(company["name"], snap)
    return res


def run_watch(profile, only: list[str] | None = None) -> WatchRunResult:
    """Обойти все компании конфига (или только перечисленные по имени)."""
    from agents import hh_api

    cfg = load_config()
    accept = TitleFilter(cfg)
    companies = [c for c in cfg.get("companies", []) if c.get("channel", "site") != "off"]
    if only:
        wanted = {n.lower() for n in only}
        companies = [c for c in companies if c["name"].lower() in wanted]

    state = load_state()
    results: list[CompanyRunResult] = []
    errors: list[str] = []
    hh_cooldown = hh_api._cooldown_left()
    # hh-компании — по кругу: давно не обходившиеся первыми, иначе лимит
    # за прогон каждый раз доставался бы одним и тем же
    hh_names = [c["name"] for c in companies if c.get("channel", "site") == "hh"]
    hh_names.sort(key=lambda n: state["companies"].get(n, {}).get("last_run", ""))
    hh_allowed = set(hh_names[:int(cfg.get("max_hh_companies_per_run", 8))])

    for n, company in enumerate(companies):
        if n:
            time.sleep(random.uniform(*_COMPANY_DELAY))
        channel = company.get("channel", "site")
        try:
            if channel == "hh":
                if hh_cooldown:
                    res = CompanyRunResult(name=company["name"], channel="hh",
                                           error=f"hh.ru на паузе ещё ~{hh_cooldown} мин")
                elif company["name"] not in hh_allowed:
                    res = CompanyRunResult(name=company["name"], channel="hh",
                                           error="лимит hh-компаний за прогон — в следующий раз")
                else:
                    res = watch_hh_company(company, profile, cfg, accept)
                    if res.error and "rate limit" in res.error:
                        hh_cooldown = hh_api._cooldown_left() or 30
            else:
                res = watch_site_company(company, profile, cfg, accept)
        except CareerFetchError as exc:
            res = CompanyRunResult(name=company["name"], channel=channel, error=str(exc))
        except Exception as exc:  # одна компания не должна ронять прогон
            res = CompanyRunResult(name=company["name"], channel=channel,
                                   error=f"{type(exc).__name__}: {str(exc)[:100]}")
        results.append(res)
        if res.error:
            errors.append(f"{res.name}: {res.error}")
        if res.error.startswith("лимит hh-компаний"):
            continue  # не обходилась — last_run не обновляем, чтобы ротация её подняла
        state["companies"][company["name"]] = dict(
            asdict(res), last_run=datetime.now().isoformat(timespec="seconds"),
            group=company.get("group", 0),
        )

    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    save_state(state)
    return WatchRunResult(companies=results, new_total=sum(r.registered for r in results), errors=errors)


# ---------------------------------------------------------------------------
# Выборки для веб-страницы
# ---------------------------------------------------------------------------

def company_rows() -> list[dict]:
    """Компании конфига + сводка последнего прогона по каждой."""
    cfg = load_config()
    state = load_state()
    rows = []
    for c in cfg.get("companies", []):
        rec = state["companies"].get(c["name"], {})
        rows.append({
            "name": c["name"],
            "group": c.get("group", 0),
            "channel": c.get("channel", "site"),
            "url": (c.get("urls") or [c.get("site_url", "")])[0] if c.get("channel", "site") == "site"
                   else (c.get("site_url") or f"https://hh.ru/employer/{c.get('hh_employer_id', '')}"),
            "hh_employer_id": c.get("hh_employer_id", ""),
            "note": c.get("note", ""),
            "hr_email": c.get("hr_email", ""),
            "last_run": rec.get("last_run", ""),
            "found": rec.get("found", 0),
            "matched": rec.get("matched", 0),
            "registered": rec.get("registered", 0),
            "error": rec.get("error", ""),
        })
    rows.sort(key=lambda r: (r["group"], r["name"]))
    return rows


def career_triage_rows() -> list[dict]:
    """Вакансии общего триажа, пришедшие с карьерных страниц (source=career:*)."""
    from agents.hh_search import _load_state as _search_state
    rows = [
        dict(rec, company_tag=str(rec.get("source", ""))[7:])
        for rec in _search_state().values()
        if str(rec.get("source", "")).startswith("career:") and not rec.get("error")
    ]
    rows.sort(key=lambda r: -int(r.get("score", 0)))
    return rows


# ---------------------------------------------------------------------------
# CLI: python -m agents.career_watch [Компания ...]
# ---------------------------------------------------------------------------

def _load_candidate_profile():
    from core.models import CandidateProfile, ScoringGroup
    data = yaml.safe_load((BASE_DIR / "config" / "candidate_profile.yaml").read_text(encoding="utf-8"))
    return CandidateProfile(
        name=data["name"],
        target_roles=data.get("target_roles", []),
        scoring_groups={
            name: ScoringGroup(weight=g["weight"], keywords=g.get("keywords", []))
            for name, g in data.get("scoring_groups", {}).items()
        },
        red_flags=dict(data.get("red_flags", {})),
        seniority_keywords=data.get("seniority_keywords", []),
    )


def main(argv: list[str]) -> int:
    result = run_watch(_load_candidate_profile(), only=argv or None)
    for r in result.companies:
        line = (f"{r.name:<22} {r.channel:<4} найдено {r.found:>4} | по фильтру {r.matched:>3} | "
                f"новых {r.new:>3} | в триаж {r.registered:>3}")
        if r.skipped:
            line += f" | отложено {r.skipped}"
        if r.error:
            line += f" | ! {r.error}"
        print(line)
        for t in r.new_titles[:5]:
            print(f"      + {t[:80]}")
    print(f"Итого новых в триаже: {result.new_total}; ошибок: {len(result.errors)}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
