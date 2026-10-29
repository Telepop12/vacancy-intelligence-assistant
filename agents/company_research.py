"""
Ресёрч компании-работодателя по открытым источникам (21.10.2026).

Первый раздел пакета подготовки к интервью: кандидат приходит, зная
компанию, — масштаб, собственников, менеджмент, структуру бизнеса,
финансы и то, что важнее всего ИТ-руководителю: ИТ-проекты, цифровизацию
и AI, закупки ИТ-услуг. Справка делается одним вызовом модели с серверным
веб-поиском (core.llm.call_research): модель сама ищет и читает страницы и
возвращает справку по восьми темам с адресами источников.

Защита от выдумки:
  - промпт запрещает заполнять пробелы догадками: «в открытых источниках
    не найдено» — нормальный ответ;
  - адреса, которые модель указала источниками темы, сверяются с тем, что
    реально вернули поиск и чтение страниц; тема без подтверждённого
    источника помечается «не подтверждено»;
  - если поиск не вернул ничего, справка целиком помечается
    неподтверждённой.

digest() сжимает справку для других этапов подготовки: вопросы
интервьюера, вопросы работодателю, «что бы вы улучшили», структура и
персонал, рассказ о себе и план 100 дней.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
# Архив справок по компаниям (21.10.2026, просьба заказчика: веб-поиск
# платный). Генерация сначала смотрит сюда и идёт в поиск, только если
# записи нет или она старше полугода.
ARCHIVE_DIR = BASE_DIR / "output" / "companies"
ARCHIVE_MAX_AGE_DAYS = 183

# Темы справки: ключ, заголовок, что искать.
TOPICS: list[tuple[str, str, str]] = [
    ("scale", "Масштаб и география",
     "сотрудники, площадки и филиалы, города и регионы, доля рынка, место в рейтингах"),
    ("owners", "Собственники и группа",
     "акционеры и бенефициары, холдинг или фонд, недавние сделки с долями"),
    ("management", "Менеджмент",
     "генеральный директор и ключевые топ-менеджеры, ИТ-директор или CDTO, если публичен; недавние смены"),
    ("structure", "Структура бизнеса",
     "юрлица, направления и бренды, сделки M&A, как устроено управление сетью или филиалами"),
    ("finance", "Финансовые показатели",
     "выручка и чистая прибыль за 2–3 последних года с динамикой, долговая нагрузка, если публична"),
    ("it", "ИТ-проекты и ИТ-ландшафт",
     "внедрённые системы (ERP, CRM, BI, отраслевые), проекты с интеграторами, стек по ИТ-вакансиям компании"),
    ("digital", "Цифровизация и AI",
     "цифровые продукты и каналы для клиентов, AI-инициативы, заявления руководства о цифровой стратегии"),
    ("procurement", "Закупки ИТ-услуг и подрядчики",
     "тендеры на ИТ, крупные контракты, ключевые вендоры и интеграторы"),
]
NOT_FOUND = "в открытых источниках не найдено"
_TITLES = {k: t for k, t, _ in TOPICS}


@dataclass
class Source:
    url: str = ""
    title: str = ""


@dataclass
class CompanySection:
    key: str = ""
    topic: str = ""
    text: str = ""
    sources: list[str] = field(default_factory=list)   # адреса, подтверждённые поиском
    verified: bool = False                             # есть хотя бы один подтверждённый источник

    @property
    def found(self) -> bool:
        """Есть ли по теме содержание (а не «не найдено»)."""
        low = self.text.lower()
        return bool(self.text.strip()) and not ("не найдено" in low and len(low) < 120)


@dataclass
class CompanyProfile:
    company: str = ""            # как в вакансии
    legal_name: str = ""         # юрлицо и бренд по данным поиска
    summary: str = ""
    sections: list[CompanySection] = field(default_factory=list)
    talking_points: list[str] = field(default_factory=list)   # как использовать на интервью
    gaps: str = ""               # чего не нашлось и что выяснить на встрече
    sources: list[Source] = field(default_factory=list)       # процитированные адреса с заголовками
    searches: int = 0
    researched_at: str = ""
    note: str = ""               # предупреждение: поиск пуст, ошибки инструмента
    from_archive: bool = False   # взято из архива, а не из свежего поиска

    @property
    def empty(self) -> bool:
        return not (self.summary or any(s.found for s in self.sections))


def from_dict(d: dict | None) -> CompanyProfile:
    """Профиль из сохранённого пакета; незнакомые ключи отбрасываются."""
    d = d if isinstance(d, dict) else {}
    secs = []
    for s in d.get("sections") or []:
        if isinstance(s, dict):
            secs.append(CompanySection(
                key=str(s.get("key") or ""), topic=str(s.get("topic") or ""),
                text=str(s.get("text") or ""),
                sources=[str(u) for u in s.get("sources") or []],
                verified=bool(s.get("verified")),
            ))
    return CompanyProfile(
        company=str(d.get("company") or ""), legal_name=str(d.get("legal_name") or ""),
        summary=str(d.get("summary") or ""), sections=secs,
        talking_points=[str(x) for x in d.get("talking_points") or []],
        gaps=str(d.get("gaps") or ""),
        sources=[Source(url=str(x.get("url") or ""), title=str(x.get("title") or ""))
                 for x in d.get("sources") or [] if isinstance(x, dict)],
        searches=int(d.get("searches") or 0), researched_at=str(d.get("researched_at") or ""),
        note=str(d.get("note") or ""), from_archive=bool(d.get("from_archive")),
    )


# ---------------------------------------------------------------------------
# Промпт
# ---------------------------------------------------------------------------

SYSTEM = """\
Отвечай на деловом русском языке, коротко и по делу, без канцелярита и
ИИ-штампов.

Ты — аналитик executive search. Кандидат идёт на собеседование на позицию
ИТ-руководителя; ты готовишь ему справку о компании-работодателе по
ОТКРЫТЫМ ИСТОЧНИКАМ с помощью веб-поиска и чтения страниц.

Где искать: официальный сайт, раздел «о компании», пресс-релизы;
rusprofile.ru, checko.ru, list-org.com, audit-it.ru, e-disclosure.ru
(юрлицо, выручка, прибыль, учредители); TAdviser, CNews, ComNews, Forbes,
РБК, «Ведомости», отраслевые СМИ; кейсы вендоров и интеграторов;
ИТ-вакансии самой компании на hh.ru (стек и устройство ИТ);
zakupki.gov.ru, b2b-center.ru и другие площадки (закупки ИТ). Ищи
по-русски — по бренду и по юрлицу.

ПРАВИЛА:
1. Только то, что нашёл в источниках, с адресом страницы. Не нашёл —
   пиши «в открытых источниках не найдено»; пробелы не заполняй догадками
   и общими знаниями.
2. Цифры — с годом и источником; если источники расходятся, приведи оба.
3. Не перепутай компанию с тёзками: сверяй бренд, юрлицо, город и отрасль
   с текстом вакансии.
4. Интерпретации («что это значит для ИТ-руководителя») — только в
   talking_points и только как гипотезы.
5. Экономь поиски: 6–10 запросов, не повторяй один и тот же.

Отвечай строго валидным JSON без markdown вокруг."""

USER = """\
ВАКАНСИЯ: {title}
КОМПАНИЯ (как указана в вакансии): {company}
---
{vacancy_text}
---

Собери справку по восьми темам (ключ — заголовок: что искать):
{topics}

Верни ТОЛЬКО валидный JSON:
{{
  "legal_name": "юрлицо и бренд (ИНН, если нашёл)",
  "summary": "2-3 предложения: кто они, чем зарабатывают, какой масштаб",
  "sections": [
    {{"key": "scale|owners|management|structure|finance|it|digital|procurement",
      "text": "2-5 предложений фактов с годами и цифрами либо «в открытых источниках не найдено»",
      "sources": ["полный адрес страницы, откуда взят факт"]}}
  ],
  "talking_points": ["3-5 пунктов: факт о компании → как уместно упомянуть его на интервью ИТ-руководителя"],
  "gaps": "1-2 предложения: чего не нашлось и что выяснить на встрече"
}}
sections — ровно 8, по одной на каждую тему, в указанном порядке."""


def topics_text() -> str:
    return "\n".join(f"- {k} — {t}: {hint}" for k, t, hint in TOPICS)


# ---------------------------------------------------------------------------
# Сверка источников
# ---------------------------------------------------------------------------

def _norm(url: str) -> str:
    """Адрес для сравнения: без схемы, www, якоря и завершающего слэша."""
    u = (url or "").strip()
    if not u.lower().startswith(("http://", "https://")):
        return ""
    p = urlsplit(u)
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/")
    return host + path + (f"?{p.query}" if p.query else "")


def _host(norm: str) -> str:
    """Сайт из нормализованного адреса: «rusprofile.ru»."""
    return norm.split("/", 1)[0].split("?", 1)[0]


def url_domain(url: str) -> str:
    """Домен для подписи ссылки: «rusprofile.ru»."""
    n = _norm(url)
    return _host(n) if n else (url or "")


def verify_urls(urls, seen: list[dict]) -> list[str]:
    """
    Оставить адреса, которые реально вернули поиск или чтение страниц:
    точное совпадение адреса или того же сайта (модель иногда укорачивает
    путь). Адрес с сайта, где поиск не был, — выдумка, отбрасывается.
    """
    seen_norm = {_norm(s.get("url", "")) for s in seen or []} - {""}
    domains = {_host(n) for n in seen_norm}
    out: list[str] = []
    for raw in urls or []:
        u = str(raw).strip()
        n = _norm(u)
        if n and (n in seen_norm or _host(n) in domains) and u not in out:
            out.append(u)
    return out


def _key_of(item: dict) -> str:
    key = str(item.get("key") or "").strip().lower()
    if key in _TITLES:
        return key
    topic = str(item.get("topic") or "").strip().lower()
    for k, title in _TITLES.items():
        if topic and (topic.startswith(title.lower()[:12]) or title.lower().startswith(topic[:12])):
            return k
    return ""


def build_profile(company: str, data: dict, seen: list[dict], searches: int = 0,
                  errors: list[str] | None = None) -> CompanyProfile:
    """Профиль из ответа модели: темы по порядку, источники сверены с поиском."""
    data = data if isinstance(data, dict) else {}
    titles = {_norm(s.get("url", "")): str(s.get("title") or "") for s in seen or []}
    raw: dict[str, dict] = {}
    for item in data.get("sections") or []:
        if isinstance(item, dict):
            key = _key_of(item)
            if key and key not in raw:
                raw[key] = item
    sections: list[CompanySection] = []
    cited: list[str] = []
    for key, topic, _hint in TOPICS:
        item = raw.get(key, {})
        text = " ".join(str(item.get("text") or "").split()) or NOT_FOUND
        urls = verify_urls(item.get("sources"), seen)
        for u in urls:
            if u not in cited:
                cited.append(u)
        sections.append(CompanySection(key=key, topic=topic, text=text, sources=urls,
                                       verified=bool(urls)))
    notes = []
    if not titles:
        notes.append("Веб-поиск не вернул результатов — справка не подтверждена источниками, "
                      "проверьте факты вручную.")
        # Коды ошибок инструментов показываем, только когда они объясняют пустой
        # поиск: единичный url_too_long при 20 найденных источниках — шум.
        if errors:
            notes.append("Ошибки поиска: " + ", ".join(sorted(set(errors))) + ".")
    return CompanyProfile(
        company=company,
        legal_name=" ".join(str(data.get("legal_name") or "").split()),
        summary=" ".join(str(data.get("summary") or "").split()),
        sections=sections,
        talking_points=[" ".join(str(x).split()) for x in data.get("talking_points") or []
                        if str(x).strip()][:6],
        gaps=" ".join(str(data.get("gaps") or "").split()),
        sources=[Source(url=u, title=titles.get(_norm(u)) or url_domain(u)) for u in cited],
        searches=int(searches or 0),
        researched_at=datetime.now().isoformat(timespec="minutes"),
        note=" ".join(notes),
    )


def digest(profile: CompanyProfile | None, max_chars: int = 3500) -> str:
    """Сжатая справка для промптов других этапов; темы «не найдено» опускаются."""
    if profile is None or profile.empty:
        return "— справка о компании не собрана: опирайся на текст вакансии —"
    head = " ".join(x for x in (profile.legal_name or profile.company, profile.summary) if x)
    lines = [head]
    for s in profile.sections:
        if s.found:
            mark = "" if s.verified else " [не подтверждено источником]"
            lines.append(f"- {s.topic}: {s.text}{mark}")
    if profile.note:
        lines.append(f"Внимание: {profile.note}")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit("\n", 1)[0] + "\n…[справка сокращена]"


# ---------------------------------------------------------------------------
# Вызовы модели
# ---------------------------------------------------------------------------

def _call_research(api_key: str, system: str, prompt: str, *, max_tokens: int = 16000,
                   purpose: str = "prep", max_searches: int = 10, max_fetches: int = 5,
                   cached_prefix: str | None = None):
    """Тонкая обёртка над шлюзом (подменяется в тестах)."""
    from core import llm
    return llm.call_research(system, prompt, max_tokens=max_tokens, api_key=api_key,
                             purpose=purpose, max_searches=max_searches, max_fetches=max_fetches,
                             cached_prefix=cached_prefix)


def research_company(company: str, title: str, vacancy_text: str, *, api_key: str,
                     purpose: str = "prep") -> CompanyProfile:
    """Справка о компании по открытым источникам (один вызов модели с веб-поиском)."""
    res = _call_research(api_key, SYSTEM, USER.format(
        title=title or "—", company=company or "—",
        vacancy_text=(vacancy_text or "— текст вакансии недоступен —")[:6000],
        topics=topics_text(),
    ), purpose=purpose)
    return build_profile(company, res.data, res.sources, res.searches, res.errors)


def ask_with_search(api_key: str, system: str, prompt: str, *,
                    purpose: str = "prep", materials: str = "") -> tuple[dict, list[str]]:
    """
    Короткий ответ с веб-поиском (вопрос кандидата в разделе «О компании»):
    (JSON модели, адреса из поля sources, подтверждённые поиском).
    materials — резюме и факт-база кандидата, первый блок системного промпта.
    """
    res = _call_research(api_key, system, prompt, max_tokens=6000, purpose=purpose,
                         max_searches=3, max_fetches=2, cached_prefix=materials or None)
    return res.data, verify_urls(res.data.get("sources"), res.sources)


# ---------------------------------------------------------------------------
# Архив справок по компаниям
# ---------------------------------------------------------------------------

_LEGAL_FORMS = r"(?:ооо|оао|зао|пао|нао|ао|ип|гк|группа компаний|холдинг|llc|ltd|inc|jsc|plc)"
_QUOTED = re.compile(r"[«\"“„]([^»\"”“]{2,80})[»\"”“]")


def company_key(name: str) -> str:
    """
    Ключ компании для архива: бренд в кавычках, если он есть, без
    организационно-правовой формы и знаков. «Сеть медицинских центров и
    клиник «СМ-Клиника»» и «ООО «СМ-Клиника»» дают один ключ «см клиника».
    """
    s = (name or "").strip().lower().replace("ё", "е")
    m = _QUOTED.search(s)
    if m:
        s = m.group(1)
    s = re.sub(rf"\b{_LEGAL_FORMS}\b\.?", " ", s)
    s = re.sub(r"[^\w]+", " ", s)
    return " ".join(s.split())


def _record_keys(company: str, profile: CompanyProfile) -> list[str]:
    """Ключи записи: название из вакансии и бренды в кавычках из юрлица."""
    keys = [company_key(company)]
    keys += [company_key(q) for q in _QUOTED.findall(profile.legal_name or "")]
    out: list[str] = []
    for k in keys:
        if k and k not in out:
            out.append(k)
    return out


def _read_record(path: Path) -> dict | None:
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return rec if isinstance(rec, dict) and isinstance(rec.get("profile"), dict) else None


def archive_lookup(company: str, max_age_days: int = ARCHIVE_MAX_AGE_DAYS,
                   now: datetime | None = None) -> CompanyProfile | None:
    """Свежая справка из архива по названию компании; None — нет записи или она устарела."""
    key = company_key(company)
    if not key or not ARCHIVE_DIR.exists():
        return None
    now = now or datetime.now()
    best: tuple[datetime, dict] | None = None
    for path in ARCHIVE_DIR.glob("*.json"):
        rec = _read_record(path)
        if rec is None or key not in (rec.get("keys") or []):
            continue
        try:
            saved = datetime.fromisoformat(str(rec.get("saved_at")))
        except ValueError:
            continue
        if now - saved > timedelta(days=max_age_days):
            continue
        if best is None or saved > best[0]:
            best = (saved, rec)
    if best is None:
        return None
    profile = from_dict(best[1]["profile"])
    profile.from_archive = True
    return profile


def archive_save(company: str, profile: CompanyProfile) -> Path | None:
    """
    Положить справку в архив. Пустую и неподтверждённую (поиск ничего не
    вернул) не кладём: иначе полгода жили бы с неудачным результатом.
    """
    keys = _record_keys(company, profile)
    if not keys or profile.empty or not profile.sources:
        return None
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / (keys[0].replace(" ", "-") + ".json")
    old = _read_record(path) if path.exists() else None
    for k in (old or {}).get("keys") or []:
        if k not in keys:
            keys.append(k)
    data = asdict(profile)
    data["from_archive"] = False
    path.write_text(json.dumps({"keys": keys, "saved_at": datetime.now().isoformat(timespec="seconds"),
                                "profile": data}, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def get_company_profile(company: str, title: str, vacancy_text: str, *, api_key: str,
                        purpose: str = "prep", force: bool = False) -> CompanyProfile:
    """
    Справка для пакета подготовки: сначала архив (не старше полугода), иначе
    веб-поиск с сохранением в архив. force=True — мимо архива (кнопка
    «Обновить ресёрч»).
    """
    if not force:
        hit = archive_lookup(company)
        if hit is not None:
            return hit
    profile = research_company(company, title, vacancy_text, api_key=api_key, purpose=purpose)
    archive_save(company, profile)
    return profile
