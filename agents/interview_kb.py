"""
Interview KB — выдержки из базы знаний о собеседованиях (data/interview_kb/).

База — три файла Markdown (~290 КБ, около 100K токенов): целиком в промпт не
влезает и не нужна. Модуль отдаёт срезы по 5–12 КБ под конкретный промпт
генератора подготовки (agents/interview_prep.py):

  question_bank()         банк реальных вопросов ИТ-директору (жанр и глубина)
  stop_words()            стоп-слова и ошибки кандидатов словами работодателей
  employer_rules()        что кандидат уровня CIO обязан выяснить у нанимателя
  process_profile(name)   профиль процесса компании из базы или типовой C-level
  presentation_rules()    самопрезентация 1–3 и 5–7 минут, «руками / делегирую»
  hundred_days_rules()    план первых 100 дней
  stories_rules()         истории и управленческие кейсы
  agenda_rules()          повестка 2026 (ИБ, ИИ, импортозамещение), деньги, возраст
  dont_say_checklist()    чек-лист «чего не говорить» с источниками (без модели)

Секции ищутся по ключевым словам заголовков («Банк вопросов», «Паттерны
процесса», «Что взять в генератор»), а не по номерам: квартальное обновление
базы может перенумеровать разделы. Разделы «Что взять в генератор» — это
нумерованные списки правил; rules(file, 1, 7) возвращает нужные пункты.

Каждая выдержка начинается со строки «[источник: файл — раздел]», чтобы
модель могла назвать источник, а resolve_sources() разворачивает метки
[S18] и «источник 8» в названия площадок из сводных таблиц базы.

Профили компаний берутся из employers_official.md: разделы «Компании с
найденными официальными страницами» (статус page), «существуют, но
содержимое не получено» (blocked) и «Не найдено» (not_found). Имена
компаний читаются из самой базы; таблица ALIASES только добавляет синонимы
(Тинькофф → Т-Банк, Вымпелком → Билайн).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
KB_DIR = BASE_DIR / "data" / "interview_kb"

FILES = {
    "employers": "employers_official.md",
    "search": "executive_search.md",
    "stories": "real_stories.md",
}

DEFAULT_MAX = 12_000

# Синонимы работодателя → имя компании, как оно записано в базе.
ALIASES: dict[str, str] = {
    "тинькофф": "Т-Банк", "tinkoff": "Т-Банк", "тбанк": "Т-Банк", "t-bank": "Т-Банк",
    "yandex": "Яндекс",
    "sber": "Сбер", "сбербанк": "Сбер", "сбертех": "Сбер",
    "вконтакте": "VK", "vk tech": "VK", "mail.ru": "VK",
    "avito": "Авито",
    "газпромнефть": "Газпром нефть", "gazprom neft": "Газпром нефть",
    "sibur": "СИБУР",
    "nlmk": "НЛМК",
    "mts": "МТС",
    "beeline": "Билайн", "вымпелком": "Билайн", "vimpelcom": "Билайн",
    "ptsecurity": "Positive Technologies", "позитив текнолоджис": "Positive Technologies",
    "kaspersky": "Лаборатория Касперского", "касперский": "Лаборатория Касперского",
    "gpb": "Газпромбанк",
    "cian": "Циан",
    "cdek": "СДЭК",
    "селектел": "Selectel",
    "rostelecom": "Ростелеком", "ртк": "Ростелеком",
    "альфабанк": "Альфа-Банк", "alfa-bank": "Альфа-Банк", "alfabank": "Альфа-Банк",
    "x5": "X5", "х5": "X5", "пятерочка": "X5", "перекресток": "X5",
    "озон": "Ozon",
    "vtb": "ВТБ",
    "rosatom": "Росатом",
    "rzd": "РЖД",
    "вайлдберриз": "Wildberries", "rwb": "Wildberries",
    "софтлайн": "Softline",
    "nornickel": "Норникель",
}


# ---------------------------------------------------------------------------
# Разбор файлов на секции
# ---------------------------------------------------------------------------

@dataclass
class Section:
    file: str          # ключ файла (employers / search / stories)
    level: int         # 2 или 3 (уровень заголовка)
    title: str         # заголовок без решёток
    body: str          # текст до следующего заголовка того же или более высокого уровня
    line: int = 0

    @property
    def text(self) -> str:
        return f"{'#' * self.level} {self.title}\n{self.body}".rstrip()


_HEADER = re.compile(r"^(#{1,4})\s+(.*\S)\s*$")


def _parse(text: str, file_key: str) -> list[Section]:
    lines = text.splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = _HEADER.match(ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    out: list[Section] = []
    for idx, (i, lvl, title) in enumerate(heads):
        end = len(lines)
        for j, l2, _t in heads[idx + 1:]:
            if l2 <= lvl:
                end = j
                break
        body = "\n".join(lines[i + 1:end]).strip("\n")
        out.append(Section(file_key, lvl, title, body, i + 1))
    return out


_cache: dict[str, tuple[float, list[Section]]] = {}


def sections(file_key: str) -> list[Section]:
    """Секции файла базы; перечитываются при изменении файла."""
    path = KB_DIR / FILES[file_key]
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    hit = _cache.get(file_key)
    if hit and hit[0] == mtime:
        return hit[1]
    secs = _parse(path.read_text(encoding="utf-8"), file_key)
    _cache[file_key] = (mtime, secs)
    return secs


def available() -> bool:
    return all((KB_DIR / f).exists() for f in FILES.values())


def find(file_key: str, *keywords: str, level: int | None = None) -> Section | None:
    """Первая секция, в заголовке которой встречаются все ключевые слова."""
    kws = [k.lower() for k in keywords]
    for s in sections(file_key):
        if level and s.level != level:
            continue
        t = s.title.lower()
        if all(k in t for k in kws):
            return s
    return None


def find_all(file_key: str, *keywords: str, level: int | None = None) -> list[Section]:
    kws = [k.lower() for k in keywords]
    return [
        s for s in sections(file_key)
        if (level is None or s.level == level) and all(k in s.title.lower() for k in kws)
    ]


def excerpt(text: str, max_chars: int = DEFAULT_MAX) -> str:
    """Обрезка по границе строки с пометкой, что выдержка сокращена."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text.rfind("\n", 0, max_chars)
    if cut < max_chars // 2:
        cut = max_chars
    return text[:cut].rstrip() + "\n…[выдержка сокращена]"


def _tag(file_key: str, note: str = "") -> str:
    return f"[источник: {FILES[file_key]}" + (f" — {note}]" if note else "]")


def _block(s: Section | None, note: str | None = None) -> str:
    if s is None:
        return ""
    return _tag(s.file, note if note is not None else s.title) + "\n" + s.body.strip()


# ---------------------------------------------------------------------------
# Нумерованные правила («Что взять в генератор», «Общие паттерны»)
# ---------------------------------------------------------------------------

_ITEM = re.compile(r"^(\d+)\.\s+(.*)$")


def numbered_items(body: str) -> dict[int, str]:
    """
    Пункты первого нумерованного списка секции. Пункт продолжается пустыми
    строками и строками с отступом; строка с начала колонки, не являющаяся
    пунктом, завершает список — дальнейшие нумерованные строки (например,
    «10 этапов» в тексте) не считаются пунктами. Работает и для списков без
    пустых строк между пунктами.
    """
    items: dict[int, str] = {}
    cur: int | None = None
    buf: list[str] = []
    ended = False

    def flush() -> None:
        if cur is not None and cur not in items:
            items[cur] = "\n".join(buf).strip()

    for ln in body.splitlines():
        m = _ITEM.match(ln)
        if m and not ended:
            flush()
            cur = int(m.group(1))
            buf = [m.group(2)]
            continue
        if cur is None:
            continue
        if ln.strip() == "" or ln[0].isspace():
            buf.append(ln.strip())
            continue
        flush()
        cur = None
        buf = []
        ended = bool(items)
    flush()
    return items


def rules(file_key: str, *nums: int) -> str:
    """Выбранные пункты раздела «Что взять в генератор подготовки»."""
    s = find(file_key, "что взять в генератор", level=2)
    if s is None:
        return ""
    items = numbered_items(s.body)
    picked = [f"{n}. {items[n]}" for n in nums if n in items]
    if not picked:
        return ""
    return _tag(file_key, s.title) + "\n" + "\n\n".join(picked)


def patterns(*nums: int) -> str:
    """Пункты раздела «Общие паттерны» (employers_official.md)."""
    s = find("employers", "общие паттерны", level=2)
    if s is None:
        return ""
    items = numbered_items(s.body)
    picked = [f"{n}. {items[n]}" for n in nums if n in items]
    if not picked:
        return ""
    return _tag("employers", s.title) + "\n" + "\n\n".join(picked)


def paragraphs_with(s: Section | None, *keywords: str) -> str:
    """Абзацы секции, содержащие все ключевые слова (без учёта регистра)."""
    if s is None:
        return ""
    kws = [k.lower() for k in keywords]
    out = []
    for para in re.split(r"\n\s*\n", s.body):
        low = para.lower()
        if all(k in low for k in kws):
            out.append(para.strip())
    return "\n\n".join(out)


def _join(*parts: str) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


# ---------------------------------------------------------------------------
# Выдержки под промпты
# ---------------------------------------------------------------------------

def question_bank(max_chars: int = DEFAULT_MAX) -> str:
    """Банк реальных вопросов: real_stories §«Банк вопросов» + вопросы CEO/масштаб/кейсы."""
    parts = [_block(find("stories", "банк вопросов", level=2))]
    for kws in (("вопросы ceo",), ("масштаб и личный вклад",),
                ("кейс-вопросы",), ("ии и импортозамещение",)):
        parts.append(_block(find("search", *kws, level=3)))
    return excerpt(_join(*parts), max_chars)


def stop_words(max_chars: int = 10_000) -> str:
    """Стоп-слова и ошибки кандидатов словами работодателей и executive search."""
    sber = paragraphs_with(find("employers", "сбер", level=3), "стоп-слова")
    parts = [
        patterns(8),
        rules("employers", 7),
        (_tag("employers", "Сбер") + "\n" + sber) if sber else "",
        _block(find("search", "типичные ошибки", level=2)),
        _block(find("search", "красные флаги", level=3)),
        rules("stories", 8),
    ]
    return excerpt(_join(*parts), max_chars)


def employer_rules(max_chars: int = 8_000) -> str:
    """Что кандидат уровня CIO обязан выяснить у нанимателя."""
    parts = [
        rules("employers", 8),
        rules("search", 9),
        rules("stories", 5, 13),
        _block(find("search", "как ведёт себя хорошая компания", level=3)),
    ]
    return excerpt(_join(*parts), max_chars)


def presentation_rules(max_chars: int = 6_000) -> str:
    """Самопрезентация 1–3 и 5–7 минут; формат достижения; «руками / делегирую»."""
    tbank = paragraphs_with(find("employers", "т-банк", level=3), "самопрезентац")
    parts = [
        rules("employers", 2, 3),
        (_tag("employers", "Т-Банк, знакомство с командой") + "\n" + tbank) if tbank else "",
        rules("search", 1, 5, 6),
        rules("stories", 3),
    ]
    return excerpt(_join(*parts), max_chars)


def hundred_days_rules(max_chars: int = 5_000) -> str:
    parts = [
        _block(find("search", "первые 100 дней", level=2)),
        rules("search", 8),
        rules("stories", 4),
    ]
    return excerpt(_join(*parts), max_chars)


def stories_rules(max_chars: int = 7_000) -> str:
    parts = [
        rules("stories", 2, 8),
        rules("search", 2, 11, 12),
        rules("employers", 4),
        _block(find("search", "кейс-вопросы", level=3)),
    ]
    return excerpt(_join(*parts), max_chars)


def agenda_rules(max_chars: int = 8_000) -> str:
    parts = [
        rules("search", 3, 7),
        rules("stories", 6, 7, 9, 10, 11),
        _block(find("stories", "безопасность и непрерывность", level=3)),
        _block(find("stories", "ии, данные", level=3)),
        _block(find("stories", "мотивация, деньги", level=3)),
    ]
    return excerpt(_join(*parts), max_chars)


def improve_rules(max_chars: int = 7_000) -> str:
    """«Что бы вы улучшили у нас»: домашняя работа по компании, кейс-блок
    «оптимизируй процесс», банк домашних заданий и кейсов."""
    parts = [
        rules("employers", 5, 6),
        _block(find("search", "домашние задания", level=3)),
        _block(find("stories", "банк кейсов", level=2)),
    ]
    return excerpt(_join(*parts), max_chars)


def team_rules(max_chars: int = 7_000) -> str:
    """«Структура и персонал»: как оценивают управление людьми — граница
    «руками / делегирую / контролирую», референсы у бывших подчинённых,
    ассессмент (микроменеджмент, делегирование), красные флаги, кейсы о
    сопротивлении изменениям и реструктуризациях."""
    parts = [
        rules("stories", 3, 12),
        _block(find("search", "референс-чек", level=3)),
        _block(find("search", "красные флаги", level=3)),
        _block(find("search", "кейс-вопросы", level=3)),
        _block(find("search", "компетенции и критерии", level=3)),
    ]
    return excerpt(_join(*parts), max_chars)


# ---------------------------------------------------------------------------
# Профиль процесса компании
# ---------------------------------------------------------------------------

@dataclass
class ProcessProfile:
    company: str = ""            # как в вакансии
    matched: str = ""            # имя компании в базе или ""
    status: str = "unknown"      # page | blocked | not_found | unknown
    summary: str = ""            # строка сводной таблицы (если есть)
    company_text: str = ""       # раздел(ы) компании из базы
    typical_text: str = ""       # типовой сценарий C-level
    sources: list[str] = field(default_factory=list)

    @property
    def status_line(self) -> str:
        if self.status == "page":
            return (f"У компании «{self.matched}» есть публичное описание процесса найма "
                    f"(прочитано 2026-09-19); ниже его разбор и сводка. Уровень страниц — "
                    f"линейные позиции, для C-level этапов больше.")
        if self.status == "blocked":
            return (f"У компании «{self.matched}» страница о процессе существует, но её "
                    f"содержимое недоступно (антибот/JS); есть только сводка по сниппету. "
                    f"Основа — типовой сценарий C-level.")
        if self.status == "not_found":
            return (f"У компании «{self.matched}» публичной страницы о процессе найма нет "
                    f"(проверено 2026-09-19). Основа — типовой сценарий C-level.")
        return ("Компании в базе знаний нет. Основа — типовой сценарий отбора C-level "
                "в РФ по данным executive search и реальных историй.")


def _norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[«»\"'`“”]", " ", s)
    s = re.sub(r"\b(ооо|ао|пао|зао|оао|нко|гк|группа компаний|холдинг|llc|ltd|inc)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _squash(s: str) -> str:
    return re.sub(r"[\s\-–—_./]", "", _norm(s))


def _name_variants(raw: str) -> list[str]:
    """«X5 Group / X5 Tech» → [«X5 Group», «X5 Tech»]; «Билайн (beelinenow …)» → [«Билайн»]."""
    raw = re.sub(r"^\d+(\.\d+)*\.?\s*", "", raw.strip())
    raw = re.sub(r"\s*\(.*?(\)|$)", " ", raw)          # скобки, в т.ч. незакрытые
    raw = re.split(r"\s+—\s+|\s*:\s+", raw)[0]
    out = []
    for part in re.split(r"\s*/\s*|\s+и\s+|\s*;\s*", raw):
        part = part.strip(" *")
        if part and len(part) >= 2:
            out.append(part)
    return out or [raw.strip(" *")]


def _matches(name_variant: str, employer: str) -> bool:
    v_norm, e_norm = _norm(name_variant), _norm(employer)
    if not v_norm or not e_norm:
        return False
    if v_norm.isascii() and len(v_norm) <= 4:
        return re.search(rf"(?<![a-z0-9]){re.escape(v_norm)}(?![a-z0-9])", e_norm) is not None
    return _squash(name_variant) in _squash(employer)


def kb_companies() -> list[tuple[str, str]]:
    """[(имя компании в базе, статус)] — page первыми, затем blocked, затем not_found."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    page = find("employers", "компании с найденными", level=2)
    if page:
        for s in sections("employers"):
            if s.level == 3 and page.line < s.line and s.line < page.line + page.body.count("\n") + 2:
                name = _name_variants(s.title)[0]
                if name not in seen:
                    seen.add(name)
                    out.append((name, "page"))

    blocked = find("employers", "содержимое не получено", level=2)
    if blocked:
        for ln in blocked.body.splitlines():
            if ln.startswith("| ") and not ln.startswith("| Компания") and not ln.startswith("|---"):
                cell = ln.strip("| ").split("|")[0].strip()
                name = _name_variants(cell)[0]
                if name and name not in seen:
                    seen.add(name)
                    out.append((name, "blocked"))

    nf = find("employers", "не найдено", level=2)
    if nf:
        for m in re.finditer(r"^\s*-\s+\*\*([^*]+)\*\*", nf.body, re.M):
            name = m.group(1).strip().rstrip(":")
            low = name.lower()
            if any(w in low for w in ("не проверялись", "таргет-лист", "дополнительный")):
                continue
            if name not in seen:
                seen.add(name)
                out.append((name, "not_found"))
    return out


def match_company(employer: str) -> tuple[str, str] | None:
    """(имя в базе, статус) для работодателя из вакансии или None."""
    employer = (employer or "").strip()
    if not employer:
        return None
    companies = kb_companies()
    e_norm = _norm(employer)
    for alias, canonical in ALIASES.items():
        if _matches(alias, e_norm):
            for name, status in companies:
                if any(_matches(canonical, v) or _matches(v, canonical) for v in _name_variants(name)):
                    return name, status
    for name, status in companies:            # порядок: page → blocked → not_found
        if any(_matches(v, employer) for v in _name_variants(name)):
            return name, status
    return None


def _summary_row(name: str) -> str:
    s = find("employers", "сводная таблица", level=2)
    if s is None:
        return ""
    for ln in s.body.splitlines():
        if ln.startswith("| ") and not ln.startswith("| Компания") and not ln.startswith("|---"):
            cell = ln.strip("| ").split("|")[0].strip()
            if any(_matches(v, cell) or _matches(cell, v) for v in _name_variants(name)):
                return ln.strip()
    return ""


def _company_sections(name: str) -> str:
    page = find("employers", "компании с найденными", level=2)
    if page is None:
        return ""
    end = page.line + page.body.count("\n") + 2
    texts = []
    for s in sections("employers"):
        if s.level == 3 and page.line < s.line < end and _name_variants(s.title)[0] == name:
            texts.append(_block(s))
    return _join(*texts)


def typical_process(max_chars: int = 10_000) -> str:
    """Типовой сценарий отбора C-level: карта этапов по умолчанию + паттерны + кто передо мной."""
    parts = [
        rules("employers", 1),
        _block(find("stories", "паттерны процесса", level=2)),
        rules("stories", 1),
        excerpt(_block(find("search", "этапы и участники", level=3)), 3_500),
        excerpt(_block(find("search", "домашние задания", level=3)), 2_000),
    ]
    return excerpt(_join(*parts), max_chars)


def process_profile(employer: str, max_chars: int = 12_000) -> ProcessProfile:
    prof = ProcessProfile(company=employer or "")
    hit = match_company(employer)
    if hit:
        prof.matched, prof.status = hit
        prof.summary = _summary_row(prof.matched)
        if prof.status == "page":
            prof.company_text = excerpt(_company_sections(prof.matched), max_chars // 2)
            prof.sources.append(f"employers_official.md — раздел «{prof.matched}»")
        elif prof.summary:
            prof.sources.append("employers_official.md — сводная таблица (по сниппету)")
    budget = max_chars - len(prof.company_text) - len(prof.summary)
    prof.typical_text = typical_process(max(4_000, budget))
    prof.sources += [
        "employers_official.md — «Что взять в генератор», п. 1 (карта этапов по умолчанию)",
        "real_stories.md — «Паттерны процесса C-level в РФ»",
        "executive_search.md — «Этапы и участники»",
    ]
    return prof


def process_text(prof: ProcessProfile) -> str:
    """Текст выдержки для промпта из профиля процесса."""
    parts = []
    if prof.summary:
        parts.append(_tag("employers", "сводная таблица, строка компании") + "\n" + prof.summary)
    if prof.company_text:
        parts.append(prof.company_text)
    parts.append(prof.typical_text)
    return _join(*parts)


# ---------------------------------------------------------------------------
# «Чего не говорить» — детерминированный чек-лист словами работодателей
# ---------------------------------------------------------------------------

DONT_SAY: list[tuple[str, str]] = [
    ("Плохие отзывы о бывшем руководстве, коллегах и команде — только факты, без эмоциональной оценки.",
     "Сбер (Хабр 688012), Билайн, Ростелеком, СДЭК — employers_official §5.8"),
    ("«Мы сделали» без «я отвечал за» — и обратная крайность, присвоение заслуг команды.",
     "Сбер, Билайн; Danilova Executive Search — executive_search §5"),
    ("Многословие: ответ длиннее 2–3 минут теряет интерес; самопрезентация — 1–3 минуты.",
     "Сбер, Билайн, IBS, Ростелеком — employers_official §5.3, §5.8"),
    ("Незнание компании: истории, места на рынке, отчётности, биографий первых лиц.",
     "Билайн, Ростелеком, НЛМК — employers_official §6.6"),
    ("«У меня нет вопросов» и «сложностей не было» — вопросы кандидата оценивают.",
     "Ростелеком, Билайн; Голубицкий — employers_official §5.9, real_stories S15"),
    ("Вопрос «как я прошёл?» в конце встречи.",
     "Альфа-Банк (Хабр 690720)"),
    ("«Защищено NDA» вместо описания масштаба: бюджет, команда, география, динамика.",
     "Альфа-Банк (Хабр 690720); Danilova — executive_search §4.3"),
    ("Расплывчатая причина ухода и эмоциональный рассказ о конфликте с топами.",
     "Сбер «стоп-слова»; Danilova; Соболева — real_stories S23"),
    ("Техническая речь с незнакомыми терминами вместо бизнес-языка денег и рисков.",
     "Голубицкий (executive_search источник 18), Odgers (источник 5), Доржиев (15)"),
    ("ИТ-бюджет как «защита расходов», а не стратегический нарратив.",
     "Доржиев, itWeek — executive_search источник 15"),
    ("Перечисление обязанностей вместо результата: «обеспечивал функционирование».",
     "Danilova (источник 8); Career Laboratory (источник 21)"),
    ("Намёк, что метите на место нанимающего; высокомерие с рекрутёром; неточности в резюме.",
     "Шурин (Д7), Забазарных / Kontakt (Д5) — executive_search §5"),
    ("Заниженный запрос по деньгам читается как недостаток амбиций — назвать минимальный и комфортный уровень.",
     "TAdviser (real_stories S12); Билайн"),
    ("Резкий отказ от «задачек» или кейсов — перевести в разбор управленческого решения.",
     "Брагин (real_stories S8), Матецкая (S20)"),
]


def dont_say_checklist() -> list[tuple[str, str]]:
    return list(DONT_SAY)


# ---------------------------------------------------------------------------
# Источники
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"\b(S\d{1,2}|A\d)\b|источник[а-я]*\s+((?:Д|М)?\d{1,2})\b", re.I)


def sources_index() -> dict[str, str]:
    """Метка → описание: S18 → «Habr — …», «источник 8» → «Данилова … — Финансы Mail»."""
    idx: dict[str, str] = {}
    for s in sections("stories"):
        m = re.match(r"^(S\d+|A\d+)\.\s+(.*)$", s.title)
        if m:
            idx[m.group(1)] = m.group(2).strip()
    for s in sections("search"):
        if s.level == 2 and "сводная таблица источников" in s.title.lower():
            for ln in s.body.splitlines():
                if not ln.startswith("| "):
                    continue
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if len(cells) >= 4 and re.fullmatch(r"(Д|М)?\d+", cells[0]):
                    idx[f"источник {cells[0]}"] = f"{cells[1]} — {cells[3]}"
    return idx


def resolve_sources(items: list[str]) -> list[str]:
    """Разворачивает метки в строках источников; неизвестные строки остаются как есть."""
    idx = sources_index()
    out: list[str] = []
    for raw in items or []:
        text = str(raw).strip()
        if not text:
            continue
        notes = []
        for m in _TAG_RE.finditer(text):
            key = m.group(1) or f"источник {m.group(2)}"
            desc = idx.get(key) or idx.get(key.upper())
            if desc and desc not in text:
                notes.append(f"{key}: {desc}")
        out.append(text + (f" ({'; '.join(notes)})" if notes else ""))
    return out


def kb_version() -> str:
    """Дата сборки базы из README (первая дата вида ГГГГ-ММ-ДД)."""
    readme = KB_DIR / "README.md"
    if not readme.exists():
        return ""
    m = re.search(r"\d{4}-\d{2}-\d{2}", readme.read_text(encoding="utf-8")[:600])
    return m.group(0) if m else ""


def quantitative_context(question: str, context: str = "", *, today: date | None = None,
                         max_chars: int = 6000) -> str:
    """Local numeric references, with complete source metadata; no network/LLM.

    Human review establishes the facts. Code checks metadata completeness,
    review dates and topic match, and never truncates a reference's caveats.
    """
    try:
        cards = yaml.safe_load((KB_DIR / "benchmarks.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return ""
    if not isinstance(cards, list):
        return ""
    now = today or date.today()
    query = question.casefold()
    full_context = (question + "\n" + context).casefold()

    def matches(terms, text):
        if not isinstance(terms, list) or not all(isinstance(t, str) and t.strip() for t in terms):
            return False
        return any(re.search(r"(?<!\w)" + re.escape(t.casefold()) + r"(?!\w)", text)
                   if len(t) <= 3 else t.casefold() in text for t in terms)

    required = ("id", "statement", "denominator", "period", "sample", "limits", "source", "url")
    blocks = []
    used = set()
    size = 0
    for card in cards:
        if not isinstance(card, dict) or not all(isinstance(card.get(k), str) and card[k].strip()
                                               for k in required):
            continue
        if card["id"] in used or not card["url"].startswith("https://"):
            continue
        try:
            checked = date.fromisoformat(str(card["checked_on"]))
            review = date.fromisoformat(str(card["review_after"]))
        except (KeyError, ValueError, TypeError):
            continue
        if not checked <= now <= review or not matches(card.get("question_terms"), query):
            continue
        if card.get("context_terms") and not matches(card["context_terms"], full_context):
            continue
        block = (f"[{card['id']}] {card['statement']}\n"
                 f"База расчёта: {card['denominator']}\n"
                 f"Период данных: {card['period']}; выборка: {card['sample']}\n"
                 f"Ограничения: {card['limits']}\n"
                 f"Источник: {card['source']} — {card['url']}\n"
                 f"Проверено: {checked.isoformat()}; пересмотреть до: {review.isoformat()}")
        if size + len(block) + (2 if blocks else 0) > max_chars:
            continue
        blocks.append(block)
        used.add(card["id"])
        size += len(block) + (2 if len(blocks) > 1 else 0)
    return "\n\n".join(blocks)
