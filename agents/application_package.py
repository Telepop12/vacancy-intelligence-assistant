"""
Application Package Layer — пакет отклика на вакансию.

Для конкретной вакансии генерирует:
  1. Сопроводительное письмо — главный пер-вакансийный артефакт на hh.ru
     (уходит мгновенно, без модерации). Спецификация заказчика: короткое
     (~120–150 слов), три части: «обо мне» → «почему я» (2–3 буллета с
     цифрами, зеркалящими требования) → заключение с конкретным следующим
     шагом. Первая строка — зацепка под боль конкретной вакансии.
  2. Рекомендацию, каким из постоянных вариантов резюме откликаться
     (см. resume_variants: на hh нельзя штамповать резюме под вакансию).

Источники фактов: каноническое резюме + факт-база data/resume/facts.md
(публикации, pet-проекты, детали «летописи»). Железное правило то же,
что и в вариантах: никакой выдумки фактов.

Артефакты: output/applications/{id}.json / {id}.md.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from agents.resume_variants import load_facts

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output" / "applications"
# Эталон письма — рамка «3+3», финальная редакция заказчика 05.10.2026 (вне git).
# Строки «>» — комментарии и в промпт не попадают.
REFERENCE_PATH = BASE_DIR / "data" / "resume" / "cover_letter_reference.md"


# Названия инструментов, которые в письме для HR уместны только если их
# называет сама вакансия (правило заказчика 23.09.2026). Проверка
# детерминированная: нашли в письме, нет в вакансии — один повтор с указанием.
TOOL_NAMES = (
    "Prometheus", "Grafana", "Zabbix", "Loki", "Jira", "Confluence", "GitLab", "GitHub",
    "Jenkins", "Kubernetes", "Docker", "Ansible", "Terraform", "Tableau", "Power BI",
    "Kafka", "PostgreSQL", "Oracle", "Elasticsearch", "Sentry", "Redis", "Airflow",
)


def stray_tool_names(letter: str, vacancy_text: str) -> list[str]:
    """Инструменты из TOOL_NAMES, которые есть в письме, но не упомянуты в вакансии."""
    low_letter, low_vac = (letter or "").lower(), (vacancy_text or "").lower()
    return [t for t in TOOL_NAMES if t.lower() in low_letter and t.lower() not in low_vac]


_SIGN_MARK = "С уважением,"
TENURE = "20+ лет"   # стаж в письме — решение заказчика 05.10.2026


def fix_tenure(letter: str) -> str:
    """Детерминированно: «29 лет»/«25+ лет» в письме → «20+ лет» (речь о стаже в управлении)."""
    return re.sub(r"\b(?:29|25\+)\s+лет\b", TENURE, letter or "")



def ensure_signature(letter: str, reference: str) -> str:
    """
    Подпись — дословно из эталона: модель иногда теряет строку с Telegram
    или портфелем. Блок от «С уважением,» до конца эталона заменяет (или
    дополняет) подпись в письме; без эталона письмо не меняется.
    """
    letter = (letter or "").rstrip()
    ref = reference or ""
    if not letter or _SIGN_MARK not in ref:
        return letter          # пустое письмо остаётся пустым — это ошибка генерации, не подпись
    sig = ref[ref.rindex(_SIGN_MARK):].strip()
    body = letter[:letter.rindex(_SIGN_MARK)].rstrip() if _SIGN_MARK in letter else letter
    return f"{body}\n\n{sig}" if body else sig


def load_reference_letter(path: Path | None = None) -> str:
    """Текст эталонного письма без строк-комментариев; '' — если файла нет."""
    path = path or REFERENCE_PATH
    if not path.exists():
        return ""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if not ln.lstrip().startswith(">")]
    return "\n".join(lines).strip()


@dataclass
class ScreenerQA:
    question: str = ""
    answer: str = ""
    value_added: str = ""   # что в ответе есть СВЕРХ резюме (источник факта)


@dataclass
class Offer:
    """Предложение в письме: задача вакансии → что готов сделать → эффект → опора в опыте."""
    task: str = ""
    offer: str = ""
    effect: str = ""
    proof: str = ""


@dataclass
class Competency:
    """Пункт блока «Ключевые компетенции и достижения, релевантные позиции» (рамка «3+3»)."""
    title: str = ""
    points: list[str] = field(default_factory=list)


@dataclass
class ApplicationPackage:
    package_id: str = ""            # hh_id или slug по времени
    vacancy_title: str = ""
    company: str = ""
    vacancy_url: str = ""
    letter: str = ""
    recommended_variant: str = ""   # ключ активного варианта (cio/cto/cdto)
    variant_name: str = ""
    variant_hh_url: str = ""        # ссылка на опубликованное резюме hh
    variant_reasoning: str = ""
    hooks: list[str] = field(default_factory=list)  # какие требования вакансии зеркалим
    offers: list[Offer] = field(default_factory=list)   # три дела после выхода; effect = ось роли
    competencies: list[Competency] = field(default_factory=list)  # три требования → три доказательства
    screener_qa: list[ScreenerQA] = field(default_factory=list)  # диалог с ИИ-скринером hh
    generated_at: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_COMMON_HEAD = """\
Отвечай исключительно на деловом русском языке, живо и без канцелярита.
Допустимые термины: AI, ERP, MLOps, ROI, P&L, KPI, CEO, CIO, CTO, CDTO, CAIO,
M&A, BI, MES, ITSM, DevOps, SLA, NPV, IRR, TCO, SDLC, ГИС, Time-to-Market,
Enterprise AI. Запрещены ИИ-штампы и пустые формулы:
«обладаю обширным опытом», «нацелен на результат», «эффективный менеджер»,
«буду рад стать частью команды» и подобные.
Запрещён контрастный оборот-финализация «X, а не Y» («…результат, а не
декларация», «не просто …, а …») — пиши утверждение без противопоставления.

Ты — консультант по executive-трудоустройству. Пишешь сопроводительные письма
для кандидата уровня CIO/CTO/CDTO/CAIO и выбираешь, какой из его постоянных
вариантов резюме лучше подходит под вакансию.

ЖЕЛЕЗНОЕ ПРАВИЛО — НИКАКОЙ ВЫДУМКИ:
- только факты из переданного резюме и факт-базы (компании, цифры, проекты);
- цифры точно как в источнике; факты со статусом «в работе» или «внутреннее»
  из факт-базы использовать НЕЛЬЗЯ — только со статусом ✅ или из резюме;
- это касается и ЦИФР ИЗ ТЕКСТА ВАКАНСИИ: если ссылаешься на цель/масштаб
  компании — переноси её цифры дословно, не искажая (перепроверь каждую);
- если требование вакансии нечем закрыть — не выдумывай, выбери другое;
- СТАЖ в письме — «20+ лет» (решение заказчика 05.10.2026: речь о стаже в
  управлении технологическим развитием, не об общем стаже); «29 лет» и
  «25+ лет» в письмах не писать.

"""

_LETTER_REQUIREMENTS = """\
ТРЕБОВАНИЯ К ПИСЬМУ — РАМКА «3+3» (единственный русскоязычный формат,
решение заказчика 05.10.2026):
три ключевых требования вакансии → три доказательства → три дела после
выхода. Не пять компетенций и десять достижений — это уже резюме.
- ОБРАЗЕЦ ФОРМАТА: в пользовательском промпте передано письмо кандидата по
  ДРУГОЙ вакансии. Повторяй его структуру, тон, плотность и подпись;
  компетенции, доказательства и предложения пиши под ЭТУ вакансию.
  Образец — НЕ источник фактов: каждая цифра, компания, продукт и эффект
  — только из резюме и факт-базы; «20+ лет» из образца — оставить (правило
  о стаже выше), а «до 100+ сотрудников» — заменить цифрой из резюме
  («30+ человек») или опустить.
- ОСИ по семейству роли — три компетенции и три предложения идут по ним:
  CIO, директор по ИТ — ИТ-стратегия / Операции и эксплуатация /
  Партнёрство с бизнесом; CDTO, цифровая трансформация — Трансформация /
  Портфель инициатив / Экономика; CAIO, директор по AI, дирекция AI —
  Портфель AI / Операционная модель AI / Экономика; CTO, технический
  директор — Архитектура и инженерия / Поставка и эксплуатация / Экономика
  и команда; иная роль — три главных требования вакансии. Каркас один.
- структура, заголовки блоков — отдельными строками, как в образце:
  1) «Добрый день!» и отдельным абзацем одна фраза: «Прошу рассмотреть моё
     резюме на позицию [название вакансии в винительном падеже, строчными
     буквами, кроме имён собственных и аббревиатур]». НЕ пересказывай
     компании её вакансию («Вы ищете…» — запрещено);
  2) абзац «Мой профиль — …»: два предложения по образцу — [лет] в
     управлении технологическим развитием и трансформацией [каких
     компаний] на стыке IT, Digital, Data и AI: от стратегии и архитектуры
     до создания команд, запуска продуктов и промышленной эксплуатации;
     второе — специализация под ось роли («Специализируюсь на интеграции
     … в единую операционную модель, ориентированную на измеримый
     бизнес-эффект»). Фокус — техническое развитие, не «управлял ИТ»;
  3) блок с заголовком «Ключевые компетенции и достижения, релевантные
     позиции:» — РОВНО ТРИ нумерованных пункта по осям роли. Пункт = одна
     строка: «[Компетенция на языке требования вакансии]. — [Одно
     доказательство-достижение: что сделал, где, с цифрой из резюме или
     факт-базы]». Не больше 35 слов на пункт, без списков «– …» внутри;
  4) блок с заголовком «Чем конкретно могу усилить компанию на этой
     позиции:» — РОВНО ТРИ буллета по тем же осям: «— [Сформировать /
     Развернуть / Связать / Выстроить …] [что]: [механизмы через запятую;
     допустим путь «идея → PoC → MVP → эксплуатация → эффект»]». Эффект
     для компании — внутри формулировки, без отдельного «это позволит»;
     без отсылок к опыту и компаниям; не больше 35 слов на буллет;
  5) заключение по образцу: «Более подробно опыт и реализованные проекты
     представлены в резюме. Буду рад обсудить задачи и приоритеты
     развития [направление из вакансии] на встрече.»;
  6) подпись — дословно из образца.
- объём — ориентир 220–280 слов, СТРОГО не больше 300: перед выдачей
  пересчитай слова, при превышении сокращай доказательства и буллеты;
- язык вакансии: используй её ключевые термины, если они подтверждены опытом;
- ЧИТАТЕЛЬ — HR, НЕ ТЕХНАРЬ: узкоспециальные термины либо не использовать,
  либо давать с пояснением в 2-3 слова; аббревиатуры за пределами
  разрешённого списка выше — только если они есть в тексте вакансии;
  названия конкретных инструментов и продуктов (Prometheus, Zabbix, Jira
  и т. п.) — только если они названы в вакансии, иначе класс: «система
  мониторинга», «трекер задач»; названия внутренних решений переводи в
  понятную пользу (AI-Security, AI-Decision Support, AI-Ops из образца —
  допустимы, они поясняются функцией).

"""

_TAIL = "Отвечай строго валидным JSON без markdown вокруг."

_SYSTEM_PROMPT = _COMMON_HEAD + _LETTER_REQUIREMENTS + _TAIL


_USER_TEMPLATE = """\
ВАКАНСИЯ:
---
{vacancy_text}
---
Название: {title} · Компания: {company}

КАНОНИЧЕСКОЕ РЕЗЮМЕ КАНДИДАТА:
---
{resume_text}
---

ФАКТ-БАЗА (дополнительные подтверждённые факты; правило статусов внутри):
---
{facts}
---

ЭТАЛОН ПИСЬМА — РАМКА «3+3» (финальная редакция кандидата по ДРУГОЙ вакансии:
повторить структуру, заголовки блоков, тон и подпись; компетенции,
доказательства и предложения — под эту вакансию; эталон НЕ источник фактов):
---
{reference}
---

ПОСТОЯННЫЕ ВАРИАНТЫ РЕЗЮМЕ КАНДИДАТА НА HH (выбери ОДИН лучший под вакансию):
{variants_list}

Верни ТОЛЬКО валидный JSON (сначала competencies — три требования вакансии по
осям роли с одним доказательством каждое, затем offers — ровно три по тем же
осям, затем письмо, собранное из них, затем выбор варианта резюме):
{{
  "competencies": [
    {{
      "title": "компетенция на языке требования вакансии (ось роли)",
      "points": ["одно доказательство-достижение: что сделал, где, с цифрой из резюме или факт-базы"]
    }}
  ],
  "offers": [
    {{
      "task": "требование или задача из текста вакансии, близко к тексту",
      "offer": "буллет: действие + что: механизмы через запятую, эффект внутри формулировки",
      "result": "ось роли, по которой идёт буллет (ИТ-стратегия / Операции / Экономика / …)"
    }}
  ],
  "letter": "полный текст письма с переносами строк \\n: обращение, фраза про резюме, абзац «Мой профиль — …», заголовок и три нумерованных пункта «N. Компетенция. — Доказательство», заголовок и три буллета «— …», заключение, подпись",
  "recommended_variant": "ключ варианта из списка",
  "variant_reasoning": "1-2 предложения: почему этот вариант под эту вакансию",
  "hooks": ["какое требование вакансии закрыто каким фактом — 2-4 пункта"]
}}
competencies — ровно три; offers — ровно три."""


# ---------------------------------------------------------------------------
# Stage 2: hh AI-screener dialogue forecast
# ---------------------------------------------------------------------------

_SCREENER_SYSTEM = """\
Отвечай исключительно на деловом русском языке, живо и без канцелярита.
Запрещены ИИ-штампы и оборот «X, а не Y».

Контекст: с 2026 года hh.ru ставит работодателям ИИ-помощника, который первым
читает отклик кандидата и задаёт уточняющие вопросы прямо в чате hh. Обычно
он переспрашивает то, что уже написано в резюме, сверяя с требованиями
вакансии («расскажите про опыт управления бюджетом», «какой у вас опыт с X»).

Твоя задача — спрогнозировать вопросы этого скринера по КОНКРЕТНОЙ вакансии
и подготовить кандидату заготовки ответов.

ЖЕЛЕЗНЫЕ ПРАВИЛА ОТВЕТОВ:
1. Ответ НЕ пересказывает строчку резюме — он ДОБАВЛЯЕТ слой сверху:
   конкретику, контекст решения, цифру, деталь из факт-базы, которой в
   резюме нет. Скринер сверяет с резюме; совпадение слово в слово выглядит
   как бот, пересказ — как пустота. Ценность = новая информация.
2. Формат чата: 2-4 коротких предложения, разговорный деловой тон, без
   приветствий и подписей. Человек печатает в чате, не пишет эссе.
3. Только факты из резюме и факт-базы; цифры дословно. Если по теме вопроса
   фактов мало — честный ответ через смежный опыт, без выдумки.
4. Анти-оверфит: не набивать ответ ключевыми словами вакансии; естественная
   речь убедительнее идеального совпадения.

Отвечай строго валидным JSON."""

_SCREENER_USER = """\
ВАКАНСИЯ:
---
{vacancy_text}
---
Название: {title} · Компания: {company}

РЕЗЮМЕ КАНДИДАТА (то, что скринер уже «прочитал»):
---
{resume_text}
---

ФАКТ-БАЗА (источник добавленной ценности — детали, которых нет в резюме):
---
{facts}
---

Верни ТОЛЬКО валидный JSON:
{{
  "screener_qa": [
    {{
      "question": "вопрос, как его задаст ИИ-скринер (по требованию вакансии)",
      "answer": "заготовка ответа в чат: 2-4 предложения, с добавленной ценностью",
      "value_added": "коротко: что в ответе есть сверх резюме и откуда факт"
    }}
  ]
}}
6-8 вопросов: по ключевым требованиям вакансии (опыт, масштаб, отрасль,
инструменты), включая 1-2 «неудобных» (зоны, где резюме кандидата слабее
требований — там скринер копнёт почти наверняка)."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_package(
    vacancy_text: str,
    title: str = "",
    company: str = "",
    url: str = "",
    package_id: str = "",
    resume_text: str | None = None,
) -> ApplicationPackage:
    """Письмо «3+3» + выбор варианта резюме + «что зеркалим» (один вызов) и прогноз скринера."""
    from agents.resume_variants import load_canonical_resume, load_variants_config

    pkg = ApplicationPackage(
        package_id=package_id or datetime.now().strftime("pkg_%Y%m%d_%H%M%S"),
        vacancy_title=title,
        company=company,
        vacancy_url=url,
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )

    api_key = _get_api_key()
    if not api_key:
        pkg.error = "Нет ANTHROPIC_API_KEY — генерация пакета отклика требует LLM"
        return pkg

    try:
        resume = resume_text or load_canonical_resume()
    except Exception as exc:
        pkg.error = f"Не удалось прочитать каноническое резюме: {exc}"
        return pkg

    all_variants = load_variants_config()["variants"]
    # Only variants actually published on hh.ru are eligible for recommendation
    vcfg = {k: v for k, v in all_variants.items() if v.get("active", True)}
    variants_list = "\n".join(
        f"- {key}: {v['name']} — фокус: {' '.join(str(v.get('focus', '')).split())}"
        for key, v in vcfg.items()
    )

    prompt = _USER_TEMPLATE.format(
        vacancy_text=vacancy_text[:6000],
        title=title or "—",
        company=company or "—",
        resume_text=resume,
        facts=load_facts() or "— факт-база пуста —",
        reference=load_reference_letter() or "— эталона нет: следуй правилам структуры из системного промпта —",
        variants_list=variants_list,
    )

    try:
        data = _call_llm(api_key, prompt)
        if ", а не " in (data.get("letter") or ""):
            # Same deterministic guard as in resume_variants: one retry
            # with direct feedback on the banned rhetoric.
            data = _call_llm(
                api_key,
                prompt + "\n\nВАЖНО: в прошлой попытке в письме был запрещённый "
                "оборот «…, а не …». Перепиши без противопоставления.",
            )
        stray = stray_tool_names(data.get("letter") or "", vacancy_text)
        if stray:
            data = _call_llm(
                api_key,
                prompt + "\n\nВАЖНО: в прошлой попытке в письме были названия "
                "инструментов, которых нет в тексте вакансии: " + ", ".join(stray)
                + ". Читатель — HR: замени их классом («система мониторинга», "
                "«трекер задач») или убери, остальное сохрани.",
            )
        pkg.letter = fix_tenure(ensure_signature((data.get("letter") or "").strip(), load_reference_letter()))
        pkg.recommended_variant = data.get("recommended_variant", "")
        rec_cfg = vcfg.get(pkg.recommended_variant, {})
        pkg.variant_name = rec_cfg.get("name", pkg.recommended_variant)
        pkg.variant_hh_url = rec_cfg.get("hh_url", "") or ""
        pkg.variant_reasoning = data.get("variant_reasoning", "")
        pkg.hooks = data.get("hooks") or []
        pkg.competencies = [
            Competency(title=str(c.get("title", "")), points=[str(x) for x in c.get("points") or []])
            for c in data.get("competencies") or [] if isinstance(c, dict)
        ]
        pkg.offers = [
            Offer(task=str(o.get("task", "")), offer=str(o.get("offer", "")),
                  effect=str(o.get("result") or o.get("effect") or ""))   # effect = ось роли
            for o in data.get("offers") or [] if isinstance(o, dict)
        ]
        if not pkg.letter:
            pkg.error = "LLM вернул пустое письмо — повторите генерацию"
            return pkg

        # Stage 2: прогноз диалога с ИИ-скринером hh (не фатально при сбое —
        # пакет с письмом ценен и без него)
        try:
            data2 = _call_screener(
                _SCREENER_USER.format(
                    vacancy_text=vacancy_text[:6000],
                    title=title or "—", company=company or "—",
                    resume_text=resume, facts=load_facts() or "— факт-база пуста —",
                ),
            )
            pkg.screener_qa = [
                ScreenerQA(**{k: q.get(k, "") for k in ("question", "answer", "value_added")})
                for q in data2.get("screener_qa") or []
            ]
        except Exception:
            pkg.screener_qa = []

        _save_package(pkg)
    except Exception as exc:
        pkg.error = f"Ошибка генерации: {exc}"

    return pkg


def load_saved_package(package_id: str) -> ApplicationPackage | None:
    path = OUTPUT_DIR / f"{_safe_id(package_id)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["screener_qa"] = [ScreenerQA(**q) for q in data.get("screener_qa", [])]
        data["offers"] = [Offer(**o) for o in data.get("offers", [])]
        data["competencies"] = [Competency(**c) for c in data.get("competencies", [])]
        known = {f.name for f in fields(ApplicationPackage)}
        # пакеты 05.10 с двумя письмами: ключи второго письма больше не поля — отбрасываются
        return ApplicationPackage(**{k: v for k, v in data.items() if k in known})
    except (json.JSONDecodeError, TypeError):
        return None


def letter_word_count(letter: str) -> int:
    return len(re.findall(r"[\w\-—']+", letter, re.UNICODE))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _safe_id(package_id: str) -> str:
    return re.sub(r"[^\w\-]", "_", package_id)


def _save_package(pkg: ApplicationPackage) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sid = _safe_id(pkg.package_id)
    (OUTPUT_DIR / f"{sid}.json").write_text(
        json.dumps(asdict(pkg), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    md = [
        f"# Пакет отклика: {pkg.vacancy_title}",
        "",
        f"_Компания: {pkg.company} · {pkg.vacancy_url}_",
        f"_Сгенерировано: {pkg.generated_at}_",
        "",
        f"## Каким резюме откликаться: {pkg.variant_name}",
        "",
        pkg.variant_reasoning,
        "",
        "## Сопроводительное письмо (рамка «3+3»)",
        "",
        pkg.letter,
        "",
        "## Что зеркалим из вакансии",
        "",
    ]
    md += [f"- {h}" for h in pkg.hooks]
    if pkg.competencies:
        md += ["", "## Три требования → три доказательства", ""]
        for i, c in enumerate(pkg.competencies, 1):
            md += [f"{i}. **{c.title}** — " + " ".join(c.points)]
    if pkg.offers:
        md += ["", "## Три дела после выхода (ось роли)", ""]
        for o in pkg.offers:
            md += [f"- **{o.offer}** — {o.effect}", f"  _требование: {o.task}_"]
    if pkg.screener_qa:
        md += ["", "## Прогноз диалога с ИИ-скринером hh", ""]
        for q in pkg.screener_qa:
            md += [f"**🤖 {q.question}**", "", q.answer, ""]
            if q.value_added:
                md += [f"_Сверх резюме: {q.value_added}_", ""]
    (OUTPUT_DIR / f"{sid}.md").write_text("\n".join(md), encoding="utf-8")


def _call_llm(api_key: str, prompt: str) -> dict:
    """Thin wrapper over the shared gateway (kept for test monkeypatching)."""
    from core import llm
    return llm.call_json(_SYSTEM_PROMPT, prompt, max_tokens=2500, api_key=api_key)


def _call_screener(prompt: str) -> dict:
    """Stage-2 call: hh AI-screener dialogue forecast."""
    from core import llm
    return llm.call_json(_SCREENER_SYSTEM, prompt, max_tokens=4000,
                         banned_substrings=[", а не "])


def _get_api_key() -> str:
    from core import llm
    return llm.get_api_key()
