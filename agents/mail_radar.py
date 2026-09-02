"""
Mail Radar — разбор почтовых рассылок с вакансиями (LinkedIn / hh.ru).

Gmail MCP доступен только в сессии Claude Code (сервер сам в ящик не ходит),
поэтому конвейер двухзвенный:

  1) В сессии Claude вытаскивает письма по фильтрам (ниже) и передаёт их
     как JSON-список [{sender, subject, date, body}, ...] — body в PLAIN_TEXT.
  2) Разбор здесь: `ingest_emails()` — через POST /radar/import
     или CLI `python -m agents.mail_radar emails.json`.

Судьба лидов по источникам:
  hh.ru    — из письма берётся только id вакансии; полное описание
             загружается через hh_api (JSON-LD), вакансия проходит
             rule-based триаж и попадает в общий search state
             (страницы /search, /radar, карточка вакансии).
  LinkedIn — скрейпить LinkedIn НЕЛЬЗЯ (риск бана аккаунта), поэтому лид
             хранится карточкой в radar state (название, компания, город,
             ссылка); полный текст пользователь вставляет руками — лид
             при этом помечается converted.
             Актуальность проверяется по ПУБЛИЧНОЙ гостевой странице вакансии
             (без логина и cookies аккаунта, малыми порциями, с хоста —
             из контейнера LinkedIn недоступен): маркер «Заявки на эту
             вакансию больше не принимаются» → лид уходит в архив (closed).

Фильтры писем (для сессии Claude):
  LinkedIn: from:jobalerts-noreply@linkedin.com
  hh.ru:    from:noreply@hh.ru + тема «Подходящие вакансии для резюме:»

Состояние: output/mail_radar_state.json — лиды (дедуп по source:id) и
отпечатки уже разобранных писем (повторная передача тех же писем безопасна
и не завышает счётчики). Незагруженные hh-вакансии повторяются при каждом
запуске независимо от писем; пока действует кулдаун hh — сеть не трогаем.
"""
from __future__ import annotations

import html as _html_lib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = BASE_DIR / "output" / "mail_radar_state.json"

# Не больше стольких hh-вакансий за один прогон — анти-бот hh.ru блокирует
# длинные серии запросов (см. hh_search.max_new_per_run); остаток дозагрузится
# при следующем разборе почты.
MAX_HH_FETCH_PER_RUN = 30

SOURCE_LINKEDIN = "linkedin"
SOURCE_HH = "hh"

# Статусы лида
STATUS_NEW = "new"            # ждёт решения пользователя (LinkedIn)
STATUS_TRIAGED = "triaged"    # hh-вакансия загружена и оценена в общем state
STATUS_CONVERTED = "converted"  # текст добавлен руками → полноценная вакансия
STATUS_HIDDEN = "hidden"      # пользователь скрыл лид
STATUS_ERROR = "error"        # hh-загрузка не удалась — повторим в следующий раз
STATUS_CLOSED = "closed"      # LinkedIn: «заявки больше не принимаются» (проверка страницы)

# LinkedIn-лиды старше этого срока показываются свёрнуто: вакансии там живут
# 2–4 недели, и в бэклоге половина уже закрыта.
FRESH_DAYS = 14
# Проверка актуальности: не больше стольких публичных страниц за прогон и
# случайная пауза между запросами — LinkedIn режет серии (HTTP 999 / authwall).
MAX_LI_CHECKS_PER_RUN = 40
LI_CHECK_DELAY = (2.0, 5.0)


# ---------------------------------------------------------------------------
# Модель лида
# ---------------------------------------------------------------------------

@dataclass
class MailLead:
    source: str                 # linkedin | hh
    ext_id: str                 # id вакансии на площадке
    title: str = ""
    company: str = ""
    location: str = ""
    salary: str = ""
    url: str = ""               # канонический URL без трекинг-параметров
    resume_variant: str = ""    # CIO | CDO | CTO (из темы hh-письма)
    email_date: str = ""        # дата письма (ISO)
    alert_subject: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.ext_id}"


@dataclass
class RadarIngestReport:
    emails_total: int = 0
    emails_parsed: int = 0
    emails_skipped: int = 0     # уже разбирались раньше (отпечаток в state)
    leads_found: int = 0
    new_linkedin: int = 0
    new_hh: int = 0
    triaged_hh: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Определение источника и варианта резюме
# ---------------------------------------------------------------------------

_HH_SUBJECT_MARK = "подходящие вакансии для резюме"


def detect_source(sender: str = "", subject: str = "", body: str = "") -> str:
    """Return SOURCE_* for a job-alert email, or '' when it is neither."""
    s = (sender or "").lower()
    if "jobalerts-noreply@linkedin.com" in s:
        return SOURCE_LINKEDIN
    if "hh.ru" in s and _HH_SUBJECT_MARK in (subject or "").lower():
        return SOURCE_HH
    # Фолбэк по содержимому — на случай пересланных писем без заголовков
    if "linkedin.com/comm/jobs/view/" in (body or ""):
        return SOURCE_LINKEDIN
    if _HH_SUBJECT_MARK in (subject or "").lower():
        return SOURCE_HH
    return ""


def variant_from_subject(subject: str) -> str:
    """Map an hh digest subject to the resume variant it was built for."""
    s = (subject or "").lower()
    if "технический директор" in s or "(cto" in s:
        return "CTO"
    if "цифровой трансформации" in s or "cdo" in s or "cdto" in s:
        return "CDO"
    if "информационным технологиям" in s or "(cio" in s:
        return "CIO"
    return ""


# ---------------------------------------------------------------------------
# Парсер LinkedIn-дайджеста
# ---------------------------------------------------------------------------

_LI_JOB_URL_RE = re.compile(r"https://www\.linkedin\.com/comm/jobs/view/(\d+)/", re.IGNORECASE)
_LI_SEGMENT_SPLIT_RE = re.compile(r"^\s*-{5,}\s*$", re.MULTILINE)
# Служебные строки дайджеста, которые не являются названием/компанией/городом
_LI_BOILERPLATE_PREFIXES = (
    "ваше оповещение",
    "новые вакансии",
    "новая вакансия",
    "эта компания активно",
    "подайте заявку",
    "см. вакансию",
    "см. все вакансии",
    "выполняйте поиск",
    "актуально",
)


def parse_linkedin_body(body: str, email_date: str = "", subject: str = "") -> list[MailLead]:
    """
    Разбирает plain-text дайджест LinkedIn на лиды.

    Каждая вакансия — сегмент между линиями из дефисов:
    название / компания / город / [Зарплата …] / «См. вакансию: URL».
    """
    leads: list[MailLead] = []
    for segment in _LI_SEGMENT_SPLIT_RE.split(body or ""):
        m = _LI_JOB_URL_RE.search(segment)
        if not m:
            continue
        job_id = m.group(1)

        info_lines: list[str] = []
        salary = ""
        for raw_line in segment.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            low = line.lower()
            if any(low.startswith(p) for p in _LI_BOILERPLATE_PREFIXES):
                if low.startswith("см. вакансию"):
                    break  # дальше только ссылки и футер
                continue
            if low.startswith("зарплата"):
                salary = line
                continue
            info_lines.append(line)

        leads.append(MailLead(
            source=SOURCE_LINKEDIN,
            ext_id=job_id,
            title=_html_lib.unescape(info_lines[0]) if info_lines else "",
            company=_html_lib.unescape(info_lines[1]) if len(info_lines) > 1 else "",
            location=_html_lib.unescape(info_lines[2]) if len(info_lines) > 2 else "",
            salary=salary,
            url=f"https://www.linkedin.com/jobs/view/{job_id}/",
            email_date=email_date,
            alert_subject=subject,
        ))
    return leads


# ---------------------------------------------------------------------------
# Парсер hh-дайджеста
# ---------------------------------------------------------------------------

# Строка вида: | Название вакансии[](https://hh.ru/vacancy/123?...utm_content=vacancy_name...) |
_HH_TITLE_RE = re.compile(
    r"([^|\[\]]{3,200}?)\s*\[\]\(\s*https?://hh\.ru/vacancy/(\d+)[^)]*utm_content=vacancy_name",
    re.IGNORECASE,
)
_HH_CELL_RE = re.compile(r"^\|\s*([^|\[\]]{2,100}?)\s*\|?\s*$")
# «от 500 000 ₽ за месяц», «до 800000 ₽», «300 000 – 400 000 ₽ за месяц на руки»
_HH_SALARY_CELL_RE = re.compile(r"^(от|до)\s*\d|₽|за месяц|на руки", re.IGNORECASE)
_HH_SERVICE_CELLS = (
    "посмотреть вакансию",
    "все подходящие вакансии",
    "от проверенных работодателей",
    "новые вакансии для вашего резюме",
    "письмо",
)


def parse_hh_body(body: str, email_date: str = "", subject: str = "") -> list[MailLead]:
    """
    Разбирает plain-text дайджест hh.ru: название + id из ссылки с
    utm_content=vacancy_name, компания — первая содержательная ячейка ниже.
    Полное описание сюда не входит — его загрузит hh_api при ingest.
    """
    variant = variant_from_subject(subject)
    lines = (body or "").splitlines()
    leads: list[MailLead] = []
    seen_ids: set[str] = set()  # кнопка «Посмотреть вакансию» дублирует id

    for i, raw_line in enumerate(lines):
        m = _HH_TITLE_RE.search(raw_line)
        if not m:
            continue
        title = m.group(1).strip().lstrip("|").strip()
        vac_id = m.group(2)
        if vac_id in seen_ids:
            continue
        seen_ids.add(vac_id)

        company = ""
        salary = ""
        for next_line in lines[i + 1:i + 10]:
            if _HH_TITLE_RE.search(next_line):
                break
            cm = _HH_CELL_RE.match(next_line.strip())
            if not cm:
                continue
            cell = cm.group(1).strip()
            if not cell or cell.lower() in _HH_SERVICE_CELLS or set(cell) <= {"⠀", " "}:
                continue
            if _HH_SALARY_CELL_RE.search(cell):
                salary = salary or cell   # зарплата идёт отдельной ячейкой перед компанией
                continue
            company = cell
            break

        leads.append(MailLead(
            source=SOURCE_HH,
            ext_id=vac_id,
            title=_html_lib.unescape(title),
            company=_html_lib.unescape(company),
            salary=salary,
            url=f"https://hh.ru/vacancy/{vac_id}",
            resume_variant=variant,
            email_date=email_date,
            alert_subject=subject,
        ))
    return leads


# ---------------------------------------------------------------------------
# Общий разбор писем
# ---------------------------------------------------------------------------

def parse_emails(emails: list[dict]) -> tuple[list[MailLead], list[str], int]:
    """
    emails: [{sender, subject, date, body}, ...] → (leads, errors, parsed_count).

    Письма неизвестного источника пропускаются с записью в errors.
    """
    leads: list[MailLead] = []
    errors: list[str] = []
    parsed = 0
    for n, email in enumerate(emails, start=1):
        sender = str(email.get("sender", ""))
        subject = str(email.get("subject", ""))
        date = str(email.get("date", ""))[:10]
        body = str(email.get("body", ""))
        source = detect_source(sender, subject, body)
        if source == SOURCE_LINKEDIN:
            found = parse_linkedin_body(body, email_date=date, subject=subject)
        elif source == SOURCE_HH:
            found = parse_hh_body(body, email_date=date, subject=subject)
        else:
            errors.append(f"Письмо {n} ({subject[:60]!r}): источник не распознан")
            continue
        parsed += 1
        if not found:
            errors.append(f"Письмо {n} ({subject[:60]!r}): вакансий в тексте не найдено")
        leads.extend(found)
    return leads, errors, parsed


# ---------------------------------------------------------------------------
# Состояние радара
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("leads", {})
                data.setdefault("emails_seen", [])
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_run": "", "leads": {}, "emails_seen": []}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def set_lead_status(key: str, status: str) -> bool:
    state = load_state()
    rec = state["leads"].get(key)
    if rec is None:
        return False
    rec["status"] = status
    save_state(state)
    return True


def mark_converted_by_url(url: str, vid: str) -> None:
    """Called from the manual-add flow: a pasted vacancy closes its lead."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return
    state = load_state()
    changed = False
    for rec in state["leads"].values():
        if rec.get("url", "").rstrip("/") == url and rec.get("status") != STATUS_CONVERTED:
            rec["status"] = STATUS_CONVERTED
            rec["vid"] = str(vid)
            changed = True
    if changed:
        save_state(state)


# ---------------------------------------------------------------------------
# Ingest: лиды → состояние + триаж hh
# ---------------------------------------------------------------------------

def email_fingerprint(email: dict) -> str:
    """Отпечаток письма для дедупа между прогонами (message id, если есть)."""
    mid = str(email.get("id") or email.get("message_id") or "").strip()
    if mid:
        return f"id:{mid}"
    return "|".join((
        str(email.get("sender", "")).strip().lower(),
        str(email.get("date", ""))[:19],
        str(email.get("subject", "")).strip(),
    ))


def ingest_emails(emails: list[dict], profile) -> RadarIngestReport:
    """
    Полный цикл: новые письма → лиды → дедуп по (source, id) → hh-вакансии
    загружаются и триажатся в общий search state, LinkedIn-лиды ждут
    решения на странице /radar. Незагруженные hh-вакансии (новые и прошлые
    ошибки) повторяются при каждом вызове независимо от переданных писем.
    """
    from agents import hh_api, hh_search, vacancy_store

    report = RadarIngestReport(emails_total=len(emails))
    state = load_state()
    records = state["leads"]
    seen_emails: list[str] = state.setdefault("emails_seen", [])
    seen_set = set(seen_emails)
    now = datetime.now().isoformat(timespec="seconds")

    # ── Только новые письма: повторный прогон того же файла не завышает счётчики ──
    fresh: list[dict] = []
    for email in emails:
        fp = email_fingerprint(email)
        if fp in seen_set:
            report.emails_skipped += 1
            continue
        seen_set.add(fp)
        seen_emails.append(fp)
        fresh.append(email)

    leads, parse_errors, report.emails_parsed = parse_emails(fresh)
    report.errors.extend(parse_errors)
    report.leads_found = len(leads)

    for lead in leads:
        rec = records.get(lead.key)
        if rec is not None:
            rec["last_seen"] = now
            rec["times_seen"] = int(rec.get("times_seen", 1)) + 1
            # Парсер мог стать точнее / письмо полнее — обновляем описательные поля
            for name in ("title", "company", "location", "salary"):
                value = getattr(lead, name)
                if value:
                    rec[name] = value
            # Дайджест другого резюме мог найти ту же вакансию — дополняем
            if lead.resume_variant and lead.resume_variant not in rec.get("resume_variant", ""):
                joined = ", ".join(filter(None, [rec.get("resume_variant", ""), lead.resume_variant]))
                rec["resume_variant"] = joined
            report.duplicates += 1
            continue

        records[lead.key] = dict(
            asdict(lead),
            status=STATUS_NEW,
            vid="",
            error="",
            first_seen=now,
            last_seen=now,
            times_seen=1,
        )
        if lead.source == SOURCE_HH:
            report.new_hh += 1
        else:
            report.new_linkedin += 1

    # ── hh: всё ещё не загруженное (новые + прошлые ошибки), независимо от писем ──
    pending = [
        rec["ext_id"] for rec in records.values()
        if rec.get("source") == SOURCE_HH and rec.get("status") in (STATUS_NEW, STATUS_ERROR)
    ]
    to_fetch: list[str] = []
    for vac_id in pending:
        rec = records[f"{SOURCE_HH}:{vac_id}"]
        if hh_search.get_state_item(vac_id) is not None:
            # уже известна общему триажу (автопоиск) — не перезагружаем
            rec["status"] = STATUS_TRIAGED
            rec["vid"] = vac_id
            rec["error"] = ""
            report.triaged_hh += 1
        else:
            to_fetch.append(vac_id)

    cooldown = hh_api._cooldown_left()
    if to_fetch and cooldown:
        # Пока hh «остывает» после блокировки, любой запрос лишь продлевает её
        for vac_id in to_fetch:
            rec = records[f"{SOURCE_HH}:{vac_id}"]
            rec["status"] = STATUS_ERROR
            rec["error"] = f"hh.ru на паузе после блокировки ещё ~{cooldown} мин"
        report.errors.append(
            f"hh.ru на паузе после блокировки ещё ~{cooldown} мин — "
            f"{len(to_fetch)} вакансий загрузим при следующем разборе."
        )
        to_fetch = []

    deferred = to_fetch[MAX_HH_FETCH_PER_RUN:]
    to_fetch = to_fetch[:MAX_HH_FETCH_PER_RUN]
    for vac_id in deferred:
        rec = records[f"{SOURCE_HH}:{vac_id}"]
        rec["status"] = STATUS_ERROR
        rec["error"] = "отложена: лимит загрузок за один прогон"
    if deferred:
        report.errors.append(
            f"Отложено до следующего разбора: {len(deferred)} hh-вакансий "
            f"(лимит {MAX_HH_FETCH_PER_RUN} за прогон)."
        )

    if to_fetch:
        fetched, fetch_errors, rate_limited = hh_api.fetch_vacancies_batch(to_fetch)
        for vac_id, data in fetched.items():
            vacancy_store.save_vacancy(data, vac_id)
            hh_search.register_vacancy(
                profile, data, vac_id,
                source="mail:hh",
                resume_variant=records[f"{SOURCE_HH}:{vac_id}"].get("resume_variant", ""),
            )
            rec = records[f"{SOURCE_HH}:{vac_id}"]
            rec["status"] = STATUS_TRIAGED
            rec["vid"] = vac_id
            rec["error"] = ""
            report.triaged_hh += 1
        for vac_id, msg in fetch_errors.items():
            rec = records[f"{SOURCE_HH}:{vac_id}"]
            rec["status"] = STATUS_ERROR
            rec["error"] = msg
        unattempted = [v for v in to_fetch if v not in fetched and v not in fetch_errors]
        for vac_id in unattempted:
            rec = records[f"{SOURCE_HH}:{vac_id}"]
            rec["status"] = STATUS_ERROR
            rec["error"] = "не загружалась (остановка по rate limit)"
        if rate_limited:
            report.errors.append(
                "hh.ru временно ограничил частоту запросов — часть вакансий "
                f"({len(fetch_errors) + len(unattempted)}) будет загружена при следующем запуске."
            )

    state["last_run"] = now
    save_state(state)
    return report


# ---------------------------------------------------------------------------
# Выборки для веб-страницы
# ---------------------------------------------------------------------------

def _age_days(email_date: str) -> int:
    try:
        return max(0, (datetime.now().date() - datetime.fromisoformat(email_date[:10]).date()).days)
    except ValueError:
        return 0


def linkedin_leads(statuses: tuple[str, ...] = (STATUS_NEW,)) -> list[dict]:
    """LinkedIn-лиды с ключом и возрастом (по дате письма), свежие первыми."""
    rows = [
        dict(rec, key=key, age_days=_age_days(rec.get("email_date", "")))
        for key, rec in load_state()["leads"].items()
        if rec.get("source") == SOURCE_LINKEDIN and rec.get("status") in statuses
    ]
    rows.sort(key=lambda r: (r.get("email_date", ""), r.get("last_seen", "")), reverse=True)
    return rows


def hh_error_leads() -> list[dict]:
    return [
        dict(rec, key=key)
        for key, rec in load_state()["leads"].items()
        if rec.get("source") == SOURCE_HH and rec.get("status") == STATUS_ERROR
    ]


def mail_triage_rows() -> list[dict]:
    """Строки общего search state, пришедшие из почты (source=mail:*)."""
    from agents.hh_search import _load_state as _search_state
    rows = [
        rec for rec in _search_state().values()
        if str(rec.get("source", "")).startswith("mail:") and not rec.get("error")
    ]
    rows.sort(key=lambda r: -int(r.get("score", 0)))
    return rows


def radar_rows(include_dismissed: bool = False) -> list[dict]:
    """
    Единая лента радара в одном формате: hh из рассылок и вакансии с карьерных
    сайтов (оценены) + LinkedIn-лиды (без оценки — текст вставляется руками).
    kind: hh | career | linkedin. Сортировка — свежие первыми.
    Пропущенные («Пропустить») не показываются, если не попросить явно.
    """
    from agents import vacancy_store
    from agents.hh_search import _load_state as _search_state

    dismissed = set(vacancy_store.list_dismissed())
    rows: list[dict] = []
    for rec in _search_state().values():
        src = str(rec.get("source", ""))
        if rec.get("error"):
            continue
        if not include_dismissed and str(rec.get("hh_id", "")) in dismissed:
            continue
        if src == "mail:hh":
            kind, label = "hh", "hh · рассылка"
        elif src.startswith("career:"):
            kind, label = "career", src[len("career:"):]
        else:
            continue  # обычный автопоиск живёт на /search
        published = str(rec.get("published_at", ""))[:10]
        rows.append({
            "kind": kind, "source_label": label,
            "vid": str(rec.get("hh_id", "")), "key": "",
            "title": rec.get("title") or f"Вакансия {rec.get('hh_id', '')}",
            "url": rec.get("url", ""), "company": rec.get("company", ""),
            "area": rec.get("area", ""), "salary": rec.get("salary", ""),
            "resume_variant": rec.get("resume_variant", ""),
            "score": int(rec.get("score", 0)), "recommendation": rec.get("recommendation", ""),
            "key_matches": list(rec.get("key_matches", []))[:4],
            "date": published, "age_days": _age_days(published),
            "checked_at": "", "times_seen": 0,
        })
    for lead in linkedin_leads():
        rows.append({
            "kind": "linkedin", "source_label": "LinkedIn",
            "vid": "", "key": lead["key"],
            "title": lead.get("title") or f"Вакансия {lead.get('ext_id', '')}",
            "url": lead.get("url", ""), "company": lead.get("company", ""),
            "area": lead.get("location", ""), "salary": lead.get("salary", ""),
            "resume_variant": "", "score": None, "recommendation": "",
            "key_matches": [],
            "date": lead.get("email_date", ""), "age_days": lead.get("age_days", 0),
            "checked_at": lead.get("checked_at", ""), "times_seen": int(lead.get("times_seen", 1)),
        })
    rows.sort(key=lambda r: (r["date"], r["score"] if r["score"] is not None else -1), reverse=True)
    return rows


def dismissed_rows() -> list[dict]:
    """Пропущенные вакансии общего состояния (любой источник) — для блока «Вернуть»."""
    from agents import vacancy_store
    from agents.hh_search import _load_state as _search_state

    dismissed = set(vacancy_store.list_dismissed())
    rows = [
        {"vid": str(rec.get("hh_id", "")), "title": rec.get("title") or f"Вакансия {rec.get('hh_id', '')}",
         "company": rec.get("company", ""), "url": rec.get("url", ""), "score": int(rec.get("score", 0)),
         "source": str(rec.get("source", ""))}
        for rec in _search_state().values() if str(rec.get("hh_id", "")) in dismissed
    ]
    rows.sort(key=lambda r: -r["score"])
    return rows


# ---------------------------------------------------------------------------
# Проверка актуальности LinkedIn-лидов по публичной странице (с хоста)
# ---------------------------------------------------------------------------

class LinkedInBlocked(Exception):
    """LinkedIn перестал отдавать публичные страницы — прогон надо остановить."""


_LI_CLOSED_MARKERS = (
    'closed-job__flavor--closed',
    'class="closed-job',
    'больше не принимаются',
    'No longer accepting applications',
)
_LI_BLOCK_MARKERS = ('/authwall', '/checkpoint/', 'login?')
LI_GONE = "gone"   # маркер final_url: страница вакансии удалена (HTTP 404/410)


def linkedin_page_status(html: str, final_url: str = "") -> str:
    """
    'closed' — вакансия закрыта; 'open' — страница вакансии без маркера
    закрытия; 'blocked' — LinkedIn отдал authwall/заглушку вместо страницы.
    """
    if final_url == LI_GONE:
        return "closed"
    if any(m in (final_url or "") for m in _LI_BLOCK_MARKERS):
        return "blocked"
    if any(m in html for m in _LI_CLOSED_MARKERS):
        return "closed"
    if "<h1" not in html or len(html) < 20_000:
        return "blocked"  # заглушка без содержимого — считаем блокировкой
    return "open"


def fetch_linkedin_page(url: str, timeout: int = 25) -> tuple[str, str]:
    """GET гостевой страницы вакансии как браузер; (html, final_url)."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), resp.geturl()
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429, 999):
            raise LinkedInBlocked(f"LinkedIn ограничил доступ (HTTP {exc.code})") from exc
        if exc.code in (404, 410):
            return "", LI_GONE   # вакансия удалена с LinkedIn — это «закрыта», не ошибка
        raise


@dataclass
class LinkedInCheckReport:
    checked: int = 0
    closed: int = 0
    still_open: int = 0
    errors: int = 0
    left_unchecked: int = 0
    stopped: str = ""       # причина остановки (блокировка), если была


def check_linkedin_leads(
    max_checks: int = MAX_LI_CHECKS_PER_RUN,
    fetch=fetch_linkedin_page,
    sleep=None,
) -> LinkedInCheckReport:
    """
    Проверяет актуальность LinkedIn-лидов со статусом new: сначала те, что
    ещё не проверялись, затем давно проверенные. Закрытые → STATUS_CLOSED.
    При первом признаке блокировки прогон останавливается — остаток
    проверится в следующий раз.
    """
    import random
    import time

    sleep = sleep or (lambda: time.sleep(random.uniform(*LI_CHECK_DELAY)))
    state = load_state()
    records = state["leads"]
    queue = [
        (key, rec) for key, rec in records.items()
        if rec.get("source") == SOURCE_LINKEDIN and rec.get("status") == STATUS_NEW
    ]
    queue.sort(key=lambda kv: (kv[1].get("checked_at", ""), kv[1].get("email_date", "")))
    report = LinkedInCheckReport(left_unchecked=len(queue))
    now = datetime.now().isoformat(timespec="seconds")

    for i, (key, rec) in enumerate(queue[:max_checks]):
        if i:
            sleep()
        try:
            html, final_url = fetch(rec["url"])
            status = linkedin_page_status(html, final_url)
        except LinkedInBlocked as exc:
            report.stopped = str(exc)
            break
        except Exception as exc:  # сеть, таймаут — лид просто останется непроверенным
            rec["check_error"] = str(exc)[:120]
            report.errors += 1
            continue
        if status == "blocked":
            report.stopped = "LinkedIn отдал страницу без вакансии (authwall/заглушка)"
            break
        rec["checked_at"] = now
        rec["check_error"] = ""
        report.checked += 1
        report.left_unchecked -= 1
        if status == "closed":
            rec["status"] = STATUS_CLOSED
            rec["closed_at"] = now
            rec["closed_reason"] = "удалена" if final_url == LI_GONE else "заявки не принимаются"
            report.closed += 1
        else:
            report.still_open += 1

    save_state(state)
    return report


# ---------------------------------------------------------------------------
# CLI: python -m agents.mail_radar emails.json
# ---------------------------------------------------------------------------

def _load_candidate_profile():
    """Локальный загрузчик профиля (зеркало web.app), чтобы CLI не тянул FastAPI."""
    import yaml
    from core.models import CandidateProfile, ScoringGroup

    data = yaml.safe_load(
        (BASE_DIR / "config" / "candidate_profile.yaml").read_text(encoding="utf-8")
    )
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
    usage = ("Использование:\n"
             "  python -m agents.mail_radar <emails.json>        разбор писем\n"
             "  python -m agents.mail_radar --check-linkedin [N] проверка актуальности LinkedIn-лидов")
    if not argv:
        print(usage)
        return 2

    if argv[0] == "--check-linkedin":
        limit = int(argv[1]) if len(argv) > 1 else MAX_LI_CHECKS_PER_RUN
        rep = check_linkedin_leads(max_checks=limit)
        print(f"Проверено: {rep.checked}, закрыто: {rep.closed}, открыто: {rep.still_open}, "
              f"ошибок: {rep.errors}, осталось непроверенных: {rep.left_unchecked}")
        if rep.stopped:
            print(f"  ! Остановлено: {rep.stopped}")
        return 0

    if len(argv) != 1:
        print(usage)
        return 2
    path = Path(argv[0])
    emails = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(emails, dict):
        emails = emails.get("emails", [])
    report = ingest_emails(emails, _load_candidate_profile())
    print(f"Писем: {report.emails_total}, разобрано: {report.emails_parsed}, "
          f"уже были: {report.emails_skipped}, лидов: {report.leads_found}")
    print(f"Новых LinkedIn: {report.new_linkedin}, новых hh: {report.new_hh}, "
          f"hh затриажено: {report.triaged_hh}, дублей: {report.duplicates}")
    for e in report.errors:
        print(f"  ! {e}")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
