"""
Interview Prep Layer — «Пакет подготовки» к собеседованию по конкретной вакансии.

Ключевой принцип (инсайт заказчика): профессиональные интервьюеры тратят на
резюме пару минут, а дальше точечными глубинными вопросами проверяют, реально
ли кандидат понимает то, что написал. Поэтому вопросы строятся ОТ КАЖДОГО
УТВЕРЖДЕНИЯ РЕЗЮМЕ (каждая цифра и формулировка = поверхность атаки) и от
честных пробелов — а не из типового списка «расскажите о себе».

Интервьюер принимает ПОЗИЦИЮ ВАКАНСИИ: узкоспециализированная вакансия
(например, чистая инфраструктура) порождает дотошного «инфраструктурщика» —
это фича. Работает независимо от отклика.

«Подготовка 2.0» (спринт 2026-09-21): промпты опираются на базу знаний
data/interview_kb/ через agents/interview_kb.py — реальные вопросы, стоп-слова
работодателей, паттерны процесса C-level. Семь LLM-этапов:
  1.  Вопросы интервьюера + заготовки ответов (банк реальных вопросов как образец).
  1b. Общие и поведенческие вопросы HR (с учётом стоп-слов работодателей).
  2.  Вопросы кандидата к работодателю (полномочия, ФОТ, внутренний кандидат…).
  3.  Purple Team: AI-рекрутёр атакует ↔ AI-двойник защищается, судья оттачивает.
  4.  Процесс и «кто передо мной» (по компании из базы или типовой сценарий),
      самопрезентация 1–3 и 5–7 минут, план первых 100 дней.
  5.  Истории и управленческие кейсы — из личного файла data/resume/stories.md,
      а пока он пуст — каркасы из проектов резюме с честными пометками.
  6.  Повестка 2026 (ИБ, ИИ, импортозамещение), блиц-«экзамен», «чего не
      говорить» лично для кандидата, 5 цифр для шпаргалки.
Шпаргалка «10 минут до звонка» собирается из готового пакета без модели.

Каждый новый блок несёт список источников из базы. Ошибка одного из этапов
4–6 не роняет пакет: блок остаётся пустым, причина — в stage_errors.

Артефакты: output/prep/{id}.json / {id}.md.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from agents import interview_kb as kb
from agents.resume_variants import load_canonical_resume, load_facts

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output" / "prep"
STORIES_PATH = BASE_DIR / "data" / "resume" / "stories.md"

SCHEMA_VERSION = 2

_LANG_RULES = """\
Отвечай исключительно на деловом русском языке, живо и без канцелярита.
Допустимые термины: AI, ERP, MES, BI, ITSM, ITIL, DevOps, MLOps, ROI, P&L, KPI,
CAPEX, OPEX, SLA, CEO, CIO, CTO, CDTO, CAIO, M&A, MDM, DWH, SIEM, RAG.
Запрещены ИИ-штампы («обладаю обширным опытом», «нацелен на результат») и
контрастный оборот «X, а не Y» — пиши утверждение без противопоставления.
Формулировки должны быть понятны и HR, и профильному руководителю.
ТОЧНОСТЬ ЦИФР: цифры и факты из текста ВАКАНСИИ и из резюме кандидата
переноси дословно, не искажая и не додумывая (перепроверяй каждую цифру);
факты кандидата — только из его резюме и факт-базы."""

_SOURCES_RULE = """\
ИСТОЧНИКИ: в поле sources перечисляй только метки и адреса, которые буквально
встречаются в ВЫДЕРЖКАХ ИЗ БАЗЫ ЗНАНИЙ выше ([S18], «источник 8», URL, название
компании и площадки), 2–5 штук на блок. Ничего не выдумывай."""


# ---------------------------------------------------------------------------
# Модель пакета
# ---------------------------------------------------------------------------

@dataclass
class PrepQA:
    source: str = ""      # какое утверждение резюме / пробел породило вопрос
    question: str = ""
    answer: str = ""      # заготовка ответа на фактах
    severity: str = ""    # strong | warn | risk — насколько болезненная зона


@dataclass
class EmployerQuestion:
    question: str = ""
    why: str = ""         # что этот вопрос даёт кандидату / как звучит для нанимающего


@dataclass
class PurpleRound:
    attack: str = ""          # выпад AI-рекрутёра
    defense: str = ""         # ответ AI-двойника кандидата
    verdict: str = ""         # оценка судьи: что убедительно, что плывёт
    improved_answer: str = "" # отточенная формулировка от судьи


@dataclass
class ProcessStage:
    stage: str = ""       # «Скрининг рекрутёра», «Встреча с первым лицом»…
    who: str = ""         # кто передо мной
    duration: str = ""    # формат и длительность
    probes: str = ""      # что проверяют у кандидата на ЭТОЙ вакансии
    tip: str = ""         # как готовиться, что взять с собой


@dataclass
class ProcessMap:
    basis: str = ""             # company | typical
    company_note: str = ""      # что известно о процессе у этой компании
    total: str = ""             # этапы, сроки, кто решает, референсы — одной строкой
    stages: list[ProcessStage] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class Presentation:
    short: str = ""       # 1–3 минуты (скрининг)
    long: str = ""        # 5–7 минут (финал, знакомство с командой)
    scope_line: str = ""  # «руками / делегирую / контролирую»
    sources: list[str] = field(default_factory=list)


@dataclass
class Story:
    kind: str = ""        # conflict_top | conflict_team | failure | leader_mistake |
                          # process_change | case_scaling | case_efficiency |
                          # case_restructuring | case_crisis
    title: str = ""
    situation: str = ""
    actions: str = ""
    result: str = ""      # с цифрами
    lesson: str = ""
    origin: str = ""      # «рассказ кандидата» | «каркас из резюме»
    gaps: str = ""        # что уточнить, если каркас


@dataclass
class HundredDays:
    block1: str = ""      # дни 1–30
    block2: str = ""      # дни 31–60
    block3: str = ""      # дни 61–100
    pitch: str = ""       # устный ответ на «что будете делать в первые месяцы» (≤1 мин)
    sources: list[str] = field(default_factory=list)


@dataclass
class AgendaItem:
    topic: str = ""       # Информационная безопасность | ИИ на практике | Импортозамещение
    thesis: str = ""      # позиция кандидата, 2–3 предложения
    case: str = ""        # кейс кандидата с цифрами или честный пробел
    sources: list[str] = field(default_factory=list)


@dataclass
class BlitzQA:
    question: str = ""
    answer: str = ""


@dataclass
class DontSayItem:
    text: str = ""
    source: str = ""      # откуда правило
    personal: bool = False  # True — «для вас» от модели, False — общий чек-лист базы


@dataclass
class Improvement:
    area: str = ""        # зона улучшения, 2–5 слов
    basis: str = ""       # вакансия | компания | отрасль — на чём основана гипотеза
    signal: str = ""      # цитата из вакансии / публичный факт о компании / тренд
    hypothesis: str = ""  # что проверить и улучшить, с эффектом для бизнеса
    phrasing: str = ""    # как сказать вслух: наблюдение → гипотеза → вопрос
    check: str = ""       # что спросить, чтобы подтвердить или снять гипотезу
    backing: str = ""     # опыт кандидата с цифрами или честное «прямого опыта нет»


@dataclass
class Improvements:
    """Ответ на «что бы вы улучшили у нас?» — гипотезы со стороны."""
    frame: str = ""       # рамка ответа: как начать, как оговорить статус гипотез
    context: str = ""     # чем живёт бизнес и отрасль компании, где ИТ делает деньги
    trends: list[str] = field(default_factory=list)
    items: list[Improvement] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


@dataclass
class PrepPackage:
    package_id: str = ""
    vacancy_title: str = ""
    company: str = ""
    vacancy_url: str = ""
    interviewer_profile: str = ""   # «с чьих позиций» построены вопросы
    qa: list[PrepQA] = field(default_factory=list)
    hr_qa: list[PrepQA] = field(default_factory=list)  # общие/поведенческие от HR
    user_qa: list[PrepQA] = field(default_factory=list)  # свои вопросы пользователя
    employer_questions: list[EmployerQuestion] = field(default_factory=list)
    purple_rounds: list[PurpleRound] = field(default_factory=list)
    top_risks: list[str] = field(default_factory=list)
    top_trumps: list[str] = field(default_factory=list)   # козыри под эту вакансию
    # --- Подготовка 2.0 ---
    process: ProcessMap = field(default_factory=ProcessMap)
    presentation: Presentation = field(default_factory=Presentation)
    stories: list[Story] = field(default_factory=list)
    hundred_days: HundredDays = field(default_factory=HundredDays)
    agenda: list[AgendaItem] = field(default_factory=list)
    blitz: list[BlitzQA] = field(default_factory=list)
    dont_say: list[DontSayItem] = field(default_factory=list)
    key_numbers: list[str] = field(default_factory=list)
    improvements: Improvements = field(default_factory=Improvements)
    qa_sources: list[str] = field(default_factory=list)
    hr_sources: list[str] = field(default_factory=list)
    employer_sources: list[str] = field(default_factory=list)
    stories_origin: str = ""        # «файл историй» | «каркасы из резюме»
    kb_version: str = ""
    schema_version: int = 1         # 2 — пакет собран «Подготовкой 2.0»
    stage_errors: list[str] = field(default_factory=list)
    generated_at: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Stage 1: interviewer questions from resume claims
# ---------------------------------------------------------------------------

_QA_SYSTEM = _LANG_RULES + """

Ты — опытный дотошный интервьюер, нанимающий руководителя. Ты смотришь на
кандидата С ПОЗИЦИЙ КОНКРЕТНОЙ ВАКАНСИИ: её фокус определяет твой профиль
(вакансия про инфраструктуру — ты придирчивый инфраструктурщик; про
трансформацию — CEO, который уже обжёгся на «трансформаторах-теоретиках»).

Твой метод: резюме ты прочёл за две минуты, дальше проверяешь ГЛУБИНУ.
Каждый вопрос строится от конкретного утверждения резюме (цифры, масштаба,
формулировки) или от пробела кандидата относительно вакансии:
- цифры: «доступность 99,9% — как считали, что исключали?»
- эффекты: «снижение потерь — эффект алгоритмов или эффект появления контроля?»
- масштаб: «команда 30 против наших 100+ — почему справитесь?»
- зоны умолчания: чего в резюме НЕТ из того, что вакансии критично.

Вопросы должны быть такими, чтобы человек, НЕ делавший того, что написано,
поплыл, а реально делавший — ответил конкретикой. Банк реальных вопросов из
базы знаний — образец жанра и глубины: бери темы и уровень, не копируй дословно.

Заготовки ответов пиши от первого лица кандидата, строго на фактах его резюме
и факт-базы. Никакой выдумки: если факта нет — заготовка честно строит ответ
через смежный опыт или признание границы. Отвечай строго валидным JSON."""

_QA_USER = """\
ВАКАНСИЯ:
---
{vacancy_text}
---
Название: {title} · Компания: {company}

РЕЗЮМЕ КАНДИДАТА:
---
{resume_text}
---

ФАКТ-БАЗА (дополнительные подтверждённые факты и уточнения; статусы соблюдать):
---
{facts}
---

БАНК РЕАЛЬНЫХ ВОПРОСОВ ИТ-ДИРЕКТОРУ (выдержки из базы знаний; дословные
вопросы — в «кавычках», метки [S18] и «источник N» — ссылки на источники):
---
{kb_questions}
---

Верни ТОЛЬКО валидный JSON:
{{
  "interviewer_profile": "1-2 предложения: кто интервьюер с позиций ЭТОЙ вакансии и что для него главное",
  "qa": [
    {{
      "source": "утверждение резюме или пробел, породившие вопрос",
      "question": "сам вопрос — точечный, глубинный",
      "answer": "заготовка ответа от первого лица, на фактах, 2-4 предложения",
      "severity": "strong|warn|risk — strong: вопрос-подача для козыря; warn: надо готовиться; risk: болевая зона"
    }}
  ],
  "top_risks": ["3 главные болевые зоны кандидата под эту вакансию"],
  "top_trumps": ["3 главных козыря кандидата под эту вакансию"]
}}

Требования к qa: 10-12 вопросов; охватить и козыри (пусть кандидат готов
подать их сильно), и болевые зоны; вопросы к цифрам обязательны; 3-4 вопроса
должны быть в жанре банка реальных вопросов (стратегия и бюджет, отношения с
первым лицом, проекты и ошибки, безопасность, ИИ и импортозамещение).
Ответы (answer) — плотные, 2-3 предложения, без воды."""


# ---------------------------------------------------------------------------
# Stage 1b: general / behavioral HR questions
# ---------------------------------------------------------------------------

_HR_SYSTEM = _LANG_RULES + """

Ты — опытный HR-директор с сильной подготовкой в психологии, интервьюируешь
руководителя C-Level. Твой жанр — общие и поведенческие вопросы, НЕ технические:
самопрезентация, мотивация, стиль управления, конфликты, работа с людьми,
неудачи, отношения с первым лицом. Ты любишь ситуационные кейсы
(«ваш сотрудник регулярно срывает сроки…», «на руководителя жалуются, что
он хамит коллегам…») и слушаешь не «что», а «как» человек думает.

Заготовки ответов пиши от первого лица кандидата: живо, структурно
(ситуация → действие → результат, где уместно), с опорой на его реальный
опыт из резюме. Ответ на «расскажите о себе» затачивай под конкретную
вакансию. Без заученности и пафоса. Заготовки НЕ должны попадать в стоп-слова
работодателей из базы знаний: причины ухода — факты без эмоций, заслуги —
баланс «я / команда», без критики бывших руководителей. Отвечай строго
валидным JSON."""

_HR_USER = """\
ВАКАНСИЯ (для контекста самопрезентации):
---
{vacancy_text}
---

РЕЗЮМЕ КАНДИДАТА:
---
{resume_text}
---

СТОП-СЛОВА И ОШИБКИ КАНДИДАТОВ — словами самих работодателей и executive
search (выдержки из базы знаний):
---
{kb_stop}
---

Верни ТОЛЬКО валидный JSON:
{{
  "hr_qa": [
    {{
      "source": "тема (самопрезентация / мотивация / конфликт / стиль управления / …)",
      "question": "вопрос как его задаст HR",
      "answer": "заготовка ответа от первого лица, 2-4 предложения",
      "severity": "hr"
    }}
  ]
}}
8-10 вопросов. Обязательно включить: «Расскажите о себе» (под эту вакансию),
причину поиска работы, 1-2 ситуационных кейса про проблемных сотрудников
(срыв сроков; жалобы коллег на хамство), конфликт с генеральным директором
или собственником, управленческий стиль, неудачу/ошибку, слабые стороны,
финансовые ожидания (минимальный и комфортный уровень, без занижения)."""


# ---------------------------------------------------------------------------
# Stage 2: candidate → employer questions
# ---------------------------------------------------------------------------

_EMP_SYSTEM = _LANG_RULES + """

Ты — карьерный консультант executive-уровня. Готовишь кандидату умные вопросы
к работодателю: такие, которые (а) дают кандидату критичную для решения
информацию, (б) демонстрируют уровень мышления C-Level. Никаких банальностей
(«какой у вас соцпакет»). Отвечай строго валидным JSON."""

_EMP_USER = """\
ВАКАНСИЯ:
---
{vacancy_text}
---

КОНТЕКСТ КАНДИДАТА (коротко): {candidate_brief}

ПРАВИЛА И ПРИМЕРЫ ИЗ БАЗЫ ЗНАНИЙ (что кандидат уровня CIO обязан выяснить):
---
{kb_emp}
---

Верни ТОЛЬКО валидный JSON:
{{
  "employer_questions": [
    {{"question": "вопрос работодателю", "why": "что вопрос даёт кандидату и как звучит для нанимающего"}}
  ]
}}
8-10 вопросов. Обязательно покрыть, перефразируя под вакансию: открыт ли конкурс
внешне и есть ли внутренний кандидат; почему появилась вакансия и что с
предшественником; кто ставит цели на первые 90 дней и как измеряется успех
через год; полномочия — бюджет, ФОТ, право найма и увольнения; сколько этапов
впереди и кто на каждом; реальная поддержка изменений первым лицом."""


# ---------------------------------------------------------------------------
# Stage 3: Purple Team
# ---------------------------------------------------------------------------

_PURPLE_SYSTEM = _LANG_RULES + """

Ты проводишь Purple Team-спарринг подготовки к интервью, играя ТРИ роли:

1. АТАКУЮЩИЙ (жёсткий скептичный рекрутёр с позиций вакансии): бьёт по самым
   болезненным зонам кандидата. Выпады конкретные, неудобные, без грубости —
   так спрашивают дотошные нанимающие руководители.
2. ЗАЩИТНИК (двойник кандидата): отвечает ТОЛЬКО фактами из резюме и факт-базы,
   от первого лица. Где фактов нет — честно признаёт границу и переводит на
   смежную силу. Никакой выдумки.
3. СУДЬЯ: оценивает раунд — что в ответе убедительно, где ответ «плывёт», и
   выдаёт отточенную финальную формулировку ответа (сильнее, короче, честно).

Отвечай строго валидным JSON."""

_PURPLE_USER = """\
ВАКАНСИЯ (суть): {title} · {company}
Профиль интервьюера: {interviewer_profile}

БОЛЕВЫЕ ЗОНЫ (по ним и атаковать): {risks}

РЕЗЮМЕ КАНДИДАТА:
---
{resume_text}
---

ФАКТ-БАЗА:
---
{facts}
---

Проведи {rounds} раунда спарринга по самым болезненным зонам.
Верни ТОЛЬКО валидный JSON:
{{
  "purple_rounds": [
    {{
      "attack": "выпад рекрутёра — конкретный и неудобный",
      "defense": "ответ двойника кандидата на фактах, от первого лица",
      "verdict": "судья: что убедительно, где плывёт — 1-2 предложения",
      "improved_answer": "отточенная финальная формулировка ответа"
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Stage 4: process map, self-presentation, first 100 days
# ---------------------------------------------------------------------------

_PROC_SYSTEM = _LANG_RULES + """

Ты — консультант executive search, который готовит кандидата уровня CIO к
конкретному процессу отбора. Работаешь ТОЛЬКО на выдержках из базы знаний
(как реально устроен отбор C-level в РФ, что публикуют сами работодатели)
и на фактах кандидата из резюме и факт-базы. Если у компании есть публичное
описание процесса — опирайся на него и честно отмечай, что оно написано для
линейных позиций, а для C-level этапов больше. Если описания нет — строй
типовой сценарий C-level и так и говори.

""" + _SOURCES_RULE + """

Отвечай строго валидным JSON."""

_PROC_USER = """\
ВАКАНСИЯ: {title} · {company}
---
{vacancy_text}
---

ЧТО ИЗВЕСТНО О ПРОЦЕССЕ ОТБОРА У ЭТОЙ КОМПАНИИ: {status_line}

ВЫДЕРЖКИ ИЗ БАЗЫ ЗНАНИЙ — ПРОЦЕСС ОТБОРА:
---
{kb_process}
---

ВЫДЕРЖКИ ИЗ БАЗЫ ЗНАНИЙ — САМОПРЕЗЕНТАЦИЯ И ПЛАН ПЕРВЫХ 100 ДНЕЙ:
---
{kb_presentation}

{kb_hundred}
---

РЕЗЮМЕ КАНДИДАТА:
---
{resume_text}
---

ФАКТ-БАЗА (статусы соблюдать):
---
{facts}
---

Козыри под вакансию: {trumps}
Болевые зоны: {risks}

Верни ТОЛЬКО валидный JSON:
{{
  "process": {{
    "basis": "company|typical",
    "company_note": "2-3 предложения: что известно о процессе именно у этой компании, либо почему берём типовой сценарий C-level",
    "total": "одна строка: сколько встреч, сроки, кто принимает решение, референсы, домашние задания",
    "stages": [
      {{
        "stage": "название этапа",
        "who": "кто передо мной: роль и уровень",
        "duration": "формат и длительность (ориентир из базы)",
        "probes": "что именно проверяют у кандидата на ЭТОЙ вакансии на этом этапе",
        "tip": "как готовиться и что взять с собой"
      }}
    ],
    "sources": ["метки/адреса из выдержек"]
  }},
  "presentation": {{
    "short": "самопрезентация на 1-3 минуты для скрининга, 120-170 слов, от первого лица: кто я → компании и отрасли → текущая роль с зоной ответственности, численностью и бюджетом → 2-3 оцифрованных достижения под эту вакансию → почему эта компания",
    "long": "самопрезентация на 5-7 минут для финала и знакомства с командой, 550-750 слов, от первого лица, по схеме «задача → роль → решение → обоснование → измеримый результат → выводы» для 2-3 результатов последних лет, с бюджетом, командой и географией; один негативный кейс «сэндвичем»; 1-2 примера инициативы; завершение — почему эта роль",
    "scope_line": "2-3 предложения: что кандидат делает руками, что делегирует, как контролирует — под эту вакансию",
    "sources": ["метки/адреса из выдержек"]
  }},
  "hundred_days": {{
    "block1": "дни 1-30: аудит и риски — 4-6 предложений под эту компанию и вакансию",
    "block2": "дни 31-60: интервью с CEO/CFO/производством, 3-5 приоритетов — 4-6 предложений",
    "block3": "дни 61-100: дорожная карта и бюджет «поддержка — развитие — риски», KPI — 4-6 предложений",
    "pitch": "устный ответ на «что вы будете делать в первые месяцы?» — до 120 слов, от первого лица",
    "sources": ["метки/адреса из выдержек"]
  }}
}}
Этапов — от 4 до 8. Всё, что касается кандидата, — только факты резюме и
факт-базы; цифры вакансии — дословно."""


# ---------------------------------------------------------------------------
# Stage 5: stories and management cases
# ---------------------------------------------------------------------------

_STORIES_SYSTEM = _LANG_RULES + """

Ты — карьерный коуч executive-уровня. Готовишь кандидату истории и кейсы для
собеседования на руководящую позицию: два конфликта, провальный проект, ошибка
руководителя, изменённый процесс и четыре управленческих кейса (масштабирование,
эффективность, реструктуризация, антикризис). Формат каждой истории —
«задача → роль → решение → обоснование → измеримый результат → вывод», с
масштабом (бюджет, команда, география) и балансом «я / команда».

ЖЕЛЕЗНОЕ ПРАВИЛО. Источник историй — ЛИЧНЫЙ ФАЙЛ ИСТОРИЙ кандидата. Если для
какого-то вида истории в файле есть материал — шлифуй его (origin =
«рассказ кандидата»), не добавляя событий и цифр, которых там нет. Если
материала нет — строй КАРКАС из реального проекта резюме: какой проект и почему
он подходит под этот вид истории, какая ситуация там вероятна, какие факты
и цифры кандидат должен вспомнить (origin = «каркас из резюме», поле gaps
заполнено). Каркас никогда не выдаёт вымысел за факт: формулировки вида
«вероятно», «здесь нужна ваша история о…».

""" + _SOURCES_RULE.replace("в поле sources", "в поле sources верхнего уровня") + """

Отвечай строго валидным JSON."""

_STORIES_USER = """\
ВАКАНСИЯ: {title} · {company}
---
{vacancy_text}
---

ЛИЧНЫЙ ФАЙЛ ИСТОРИЙ КАНДИДАТА ({stories_status}):
---
{stories_text}
---

РЕЗЮМЕ КАНДИДАТА:
---
{resume_text}
---

ФАКТ-БАЗА (статусы соблюдать):
---
{facts}
---

ВЫДЕРЖКИ ИЗ БАЗЫ ЗНАНИЙ — ИСТОРИИ И КЕЙСЫ:
---
{kb_stories}
---

Верни ТОЛЬКО валидный JSON:
{{
  "stories": [
    {{
      "kind": "conflict_top|conflict_team|failure|leader_mistake|process_change|case_scaling|case_efficiency|case_restructuring|case_crisis",
      "title": "короткое название истории (компания, период, суть)",
      "situation": "задача и контекст с масштабом: 2-3 предложения",
      "actions": "роль кандидата, решение и его обоснование: 3-4 предложения, «я» и «команда» разделены",
      "result": "измеримый результат с цифрами (или что именно нужно вспомнить)",
      "lesson": "вывод, который делает историю признаком управленческой зрелости",
      "origin": "рассказ кандидата|каркас из резюме",
      "gaps": "для каркаса: 2-3 вопроса, на которые кандидату нужно ответить себе; для рассказа — пусто"
    }}
  ],
  "sources": ["метки/адреса из выдержек"]
}}
Ровно 9 историй, по одной на каждый kind в указанном порядке. Каждая история —
не длиннее 150 слов суммарно по полям situation, actions, result, lesson."""


# ---------------------------------------------------------------------------
# Stage 6: agenda 2026, blitz, personal don'ts, key numbers
# ---------------------------------------------------------------------------

_AGENDA_SYSTEM = _LANG_RULES + """

Ты — наставник ИТ-директора перед собеседованиями 2026 года. Три задачи:
1. ПОВЕСТКА 2026: по темам «информационная безопасность», «ИИ на практике»,
   «импортозамещение» дать позицию кандидата и по одному его кейсу с цифрами
   — строго из резюме и факт-базы; если кейса нет, честно сказать, чем
   закрыть пробел (смежный опыт, позиция без цифр).
2. БЛИЦ-«ЭКЗАМЕН»: короткие вопросы на определения и цифры, где ждут готового
   ответа, а не рассуждения — под домен вакансии (например RTO/RPO, ФЗ-187 и
   категорирование КИИ, TCO, ITIL-процессы, стоимость простоя, состав ИТ-бюджета).
   Ответ — 1-2 фразы, чтобы «отскакивало». Здесь допустимы общие знания
   отрасли, это не факты кандидата.
3. «ЧЕГО НЕ ГОВОРИТЬ» ЛИЧНО ДЛЯ КАНДИДАТА: 3-5 ловушек именно под его болевые
   зоны и эту вакансию, с пояснением, почему это ловушка (по материалам базы).
4. ПЯТЬ ЦИФР для шпаргалки: числа из резюме и факт-базы, которые надо помнить
   наизусть на этой вакансии, каждая в формате «число — что это — где и когда».

""" + _SOURCES_RULE + """

Отвечай строго валидным JSON."""

_AGENDA_USER = """\
ВАКАНСИЯ: {title} · {company}
---
{vacancy_text}
---

РЕЗЮМЕ КАНДИДАТА:
---
{resume_text}
---

ФАКТ-БАЗА (статусы соблюдать):
---
{facts}
---

Болевые зоны кандидата под вакансию: {risks}

ВЫДЕРЖКИ ИЗ БАЗЫ ЗНАНИЙ — ПОВЕСТКА, ДЕНЬГИ, ВОЗРАСТ, ЭКЗАМЕН:
---
{kb_agenda}
---

ОБЩИЙ ЧЕК-ЛИСТ «ЧЕГО НЕ ГОВОРИТЬ» (уже есть у кандидата; личные пункты не
должны его дублировать):
---
{dont_say_common}
---

Верни ТОЛЬКО валидный JSON:
{{
  "agenda": [
    {{
      "topic": "Информационная безопасность|ИИ на практике|Импортозамещение",
      "thesis": "позиция кандидата на языке бизнес-рисков и денег, 2-3 предложения",
      "case": "кейс кандидата с цифрами из резюме/факт-базы, 2-4 предложения; либо честное «прямого кейса нет» и чем закрыть",
      "sources": ["метки/адреса из выдержек"]
    }}
  ],
  "blitz": [
    {{"question": "короткий вопрос на определение или цифру", "answer": "1-2 фразы"}}
  ],
  "dont_say_personal": [
    {{"text": "чего не говорить именно вам на этой вакансии", "why": "почему это ловушка"}}
  ],
  "key_numbers": ["число — что это — где и когда"]
}}
agenda — ровно 3 темы в указанном порядке; blitz — 8-10 вопросов;
dont_say_personal — 3-5; key_numbers — ровно 5."""


_IMPR_SYSTEM = _LANG_RULES + """

Ты — наставник ИТ-директора перед собеседованием. Готовишь ответ на вопрос
«Что бы вы улучшили у нас?» и его варианты («что бросается в глаза», «с чего
бы начали», «как бы оптимизировали процесс X»). Нанимающий задаёт его, чтобы
понять, разбирается ли кандидат в отрасли и технологических трендах, изучил ли
компанию и прочитал ли описание вакансии; готовый рецепт от человека со
стороны никто не ждёт. Поэтому:
1. ГИПОТЕЗЫ, НЕ ДИАГНОЗЫ. Каждое предложение — гипотеза со стороны с
   оговоркой, что её надо проверить внутри; никакой критики компании и людей.
2. ТРИ ОПОРЫ, поле basis: «вакансия» — цитата или факт из текста вакансии
   (задачи, стек, боли, формулировки); «компания» — только широко известные
   публичные факты о бизнесе этой компании (масштаб, отрасль, публичные
   проекты, регуляторика); «отрасль» — тренд отрасли и технологий 2025–2026,
   значимый для этой роли. Если компания тебе не известна или это небольшая
   фирма — прямо скажи об этом в context и опирайся на вакансию и отрасль.
   Ничего не выдумывай про компанию: сомневаешься — относи к «отрасль».
3. ВЕС КАНДИДАТА: под каждую гипотезу — чем она подкреплена в опыте
   кандидата (строго из резюме и факт-базы, с цифрами), либо честно «прямого
   опыта нет — говорить как о наблюдении».
4. КАК СКАЗАТЬ ВСЛУХ: 1–2 фразы живой речи для встречи по схеме
   наблюдение → гипотеза → вопрос собеседнику. Без снисходительного тона.
5. ЧТО СПРОСИТЬ, чтобы подтвердить или снять гипотезу до того, как
   предлагать решение.
6. context: 3–5 предложений — чем живёт бизнес и отрасль компании, где ИТ
   создаёт или теряет деньги. trends: 3–5 трендов отрасли под эту роль,
   каждый одной строкой «тренд — почему важен именно здесь».
7. frame: 2–3 предложения — рамка ответа: как начать, как оговорить статус
   гипотез, чем закончить (встречный вопрос или предложение проверить в
   первые 30 дней). План 100 дней уже есть у кандидата, его не повторять.

""" + _SOURCES_RULE + """

Отвечай строго валидным JSON."""

_IMPR_USER = """ВАКАНСИЯ: {title} · {company}
---
{vacancy_text}
---

РЕЗЮМЕ КАНДИДАТА:
---
{resume_text}
---

ФАКТ-БАЗА (статусы соблюдать):
---
{facts}
---

Козыри кандидата под вакансию: {trumps}
Устный план первых месяцев (уже есть, не повторять): {hundred_pitch}

ВЫДЕРЖКИ ИЗ БАЗЫ ЗНАНИЙ — ДОМАШНЯЯ РАБОТА ПО КОМПАНИИ, КЕЙС «ОПТИМИЗИРУЙ
ПРОЦЕСС», БАНК ДОМАШНИХ ЗАДАНИЙ:
---
{kb_improve}
---

Верни ТОЛЬКО валидный JSON:
{{
  "frame": "как отвечать на «что бы вы улучшили у нас», 2-3 предложения",
  "context": "чем живёт бизнес и отрасль компании, где ИТ делает или теряет деньги, 3-5 предложений; если компания неизвестна — так и сказать",
  "trends": ["тренд — почему важен именно для этой роли"],
  "items": [
    {{
      "area": "зона улучшения, 2-5 слов",
      "basis": "вакансия|компания|отрасль",
      "signal": "на чём основано: цитата из вакансии / публичный факт о компании / тренд",
      "hypothesis": "что бы проверил и улучшил, как гипотеза, 2-3 предложения, с эффектом для бизнеса",
      "phrasing": "как сказать вслух: наблюдение → гипотеза → вопрос, 1-2 фразы",
      "check": "что спросить, чтобы подтвердить или снять гипотезу",
      "backing": "опыт кандидата с цифрами из резюме/факт-базы либо честное «прямого опыта нет»"
    }}
  ],
  "sources": ["метки/адреса из выдержек"]
}}
items — 4-6 гипотез, среди них минимум одна с basis «вакансия» и одна с basis
«отрасль»; trends — 3-5."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_prep(
    vacancy_text: str,
    title: str = "",
    company: str = "",
    url: str = "",
    package_id: str = "",
    resume_text: str | None = None,
    purple_rounds: int = 3,
    stories_text: str | None = None,
) -> PrepPackage:
    """Generate the full interview prep package for one vacancy."""
    pkg = PrepPackage(
        package_id=package_id or datetime.now().strftime("prep_%Y%m%d_%H%M%S"),
        vacancy_title=title,
        company=company,
        vacancy_url=url,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        schema_version=SCHEMA_VERSION,
        kb_version=kb.kb_version(),
    )

    api_key = _get_api_key()
    if not api_key:
        pkg.error = "Нет ANTHROPIC_API_KEY — генерация пакета подготовки требует LLM"
        return pkg

    try:
        resume = resume_text or load_canonical_resume()
    except Exception as exc:
        pkg.error = f"Не удалось прочитать каноническое резюме: {exc}"
        return pkg

    facts = load_facts() or "— факт-база пуста —"
    vac = vacancy_text[:6000]
    t, c = title or "—", company or "—"

    try:
        # Stage 1 — interviewer QA (+ банк реальных вопросов)
        kb_questions = kb.question_bank() or "— база знаний недоступна —"
        data = _call_llm(api_key, _QA_SYSTEM, _QA_USER.format(
            vacancy_text=vac, title=t, company=c,
            resume_text=resume, facts=facts, kb_questions=kb_questions,
        ), max_tokens=6000)
        pkg.interviewer_profile = data.get("interviewer_profile", "")
        pkg.qa = [_mk(PrepQA, q) for q in data.get("qa") or []]
        pkg.top_risks = data.get("top_risks") or []
        pkg.top_trumps = data.get("top_trumps") or []
        pkg.qa_sources = _static_sources(
            kb_questions, "real_stories.md — «Банк вопросов ИТ-директору»",
            "executive_search.md — «Банк вопросов от executive search и CEO»",
        )

        # Stage 1b — general / behavioral HR questions (+ стоп-слова)
        kb_stop = kb.stop_words() or "— база знаний недоступна —"
        data1b = _call_llm(api_key, _HR_SYSTEM, _HR_USER.format(
            vacancy_text=vac, resume_text=resume, kb_stop=kb_stop,
        ), max_tokens=5000)
        pkg.hr_qa = [_mk(PrepQA, q) for q in data1b.get("hr_qa") or []]
        pkg.hr_sources = _static_sources(
            kb_stop, "employers_official.md — «Общие паттерны», п. 8; стоп-слова Сбера",
            "executive_search.md — «Типичные ошибки кандидатов C-level»",
        )

        # Stage 2 — employer questions (+ правила базы)
        brief = f"{title}; козыри: {'; '.join(pkg.top_trumps[:3])}; риски: {'; '.join(pkg.top_risks[:3])}"
        kb_emp = kb.employer_rules() or "— база знаний недоступна —"
        data2 = _call_llm(api_key, _EMP_SYSTEM, _EMP_USER.format(
            vacancy_text=vac, candidate_brief=brief, kb_emp=kb_emp,
        ), max_tokens=3000)
        pkg.employer_questions = [_mk(EmployerQuestion, q) for q in data2.get("employer_questions") or []]
        pkg.employer_sources = _static_sources(
            kb_emp, "employers_official.md — «Что взять в генератор», п. 8",
            "executive_search.md — п. 9, «Как ведёт себя хорошая компания-заказчик»",
            "real_stories.md — п. 5, 13",
        )

        # Stage 3 — Purple Team
        data3 = _call_llm(api_key, _PURPLE_SYSTEM, _PURPLE_USER.format(
            title=t, company=c,
            interviewer_profile=pkg.interviewer_profile,
            risks="; ".join(pkg.top_risks) or "по рискам из резюме",
            resume_text=resume, facts=facts, rounds=purple_rounds,
        ), max_tokens=4000)
        pkg.purple_rounds = [_mk(PurpleRound, r) for r in data3.get("purple_rounds") or []]

        if not pkg.qa:
            pkg.error = "LLM вернул пустой список вопросов — повторите генерацию"
            return pkg
    except Exception as exc:
        pkg.error = f"Ошибка генерации: {exc}"
        return pkg

    # --- Подготовка 2.0: этапы 4–6 не роняют пакет ---
    _stage(pkg, "процесс, самопрезентация, 100 дней",
           lambda: _stage_process(pkg, api_key, vac, t, c, resume, facts))
    _stage(pkg, "истории и кейсы",
           lambda: _stage_stories(pkg, api_key, vac, t, c, resume, facts, stories_text))
    _stage(pkg, "повестка 2026, блиц, «чего не говорить»",
           lambda: _stage_agenda(pkg, api_key, vac, t, c, resume, facts))
    _stage(pkg, "«что бы вы улучшили у нас»",
           lambda: _stage_improve(pkg, api_key, vac, t, c, resume, facts))
    pkg.dont_say = [d for d in pkg.dont_say if d.personal] \
        + [DontSayItem(text=x, source=s, personal=False) for x, s in kb.dont_say_checklist()]

    _save(pkg)
    return pkg


def _stage(pkg: PrepPackage, name: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — этап необязательный, причина в stage_errors
        pkg.stage_errors.append(f"{name}: {exc}")


def _stage_process(pkg, api_key, vac, title, company, resume, facts) -> None:
    prof = kb.process_profile(pkg.company)
    kb_process = kb.process_text(prof) or "— база знаний недоступна —"
    kb_pres = kb.presentation_rules()
    kb_hund = kb.hundred_days_rules()
    data = _call_llm(api_key, _PROC_SYSTEM, _PROC_USER.format(
        title=title, company=company, vacancy_text=vac,
        status_line=prof.status_line, kb_process=kb_process,
        kb_presentation=kb_pres, kb_hundred=kb_hund,
        resume_text=resume, facts=facts,
        trumps="; ".join(pkg.top_trumps) or "—",
        risks="; ".join(pkg.top_risks) or "—",
    ), max_tokens=9000)
    corpus = kb_process + kb_pres + kb_hund
    p = data.get("process") or {}
    pkg.process = ProcessMap(
        basis=str(p.get("basis") or ("company" if prof.status == "page" else "typical")),
        company_note=p.get("company_note", "") or prof.status_line,
        total=p.get("total", ""),
        stages=[_mk(ProcessStage, s) for s in p.get("stages") or []],
        sources=_clean_sources(p.get("sources"), corpus, prof.sources),
    )
    pr = data.get("presentation") or {}
    pkg.presentation = Presentation(
        short=pr.get("short", ""), long=pr.get("long", ""), scope_line=pr.get("scope_line", ""),
        sources=_clean_sources(pr.get("sources"), corpus,
                               ["employers_official.md — п. 2, 3 (Билайн, МТС, Т-Банк)",
                                "executive_search.md — п. 1, 5, 6"]),
    )
    h = data.get("hundred_days") or {}
    pkg.hundred_days = HundredDays(
        block1=h.get("block1", ""), block2=h.get("block2", ""), block3=h.get("block3", ""),
        pitch=h.get("pitch", ""),
        sources=_clean_sources(h.get("sources"), corpus,
                               ["executive_search.md — «Первые 100 дней» (РШУ, Юрченко, Gartner)",
                                "real_stories.md — п. 4"]),
    )


def _stage_stories(pkg, api_key, vac, title, company, resume, facts, stories_text) -> None:
    text = stories_text if stories_text is not None else load_stories()
    filled = bool(text.strip())
    pkg.stories_origin = "файл историй" if filled else "каркасы из резюме"
    kb_stories = kb.stories_rules()
    data = _call_llm(api_key, _STORIES_SYSTEM, _STORIES_USER.format(
        title=title, company=company, vacancy_text=vac,
        stories_status=("заполнен кандидатом — шлифовать, не досочинять" if filled
                        else f"ПУСТ — строить каркасы из резюме; файл: {STORIES_PATH.name}"),
        stories_text=text if filled else "— пусто —",
        resume_text=resume, facts=facts, kb_stories=kb_stories,
    ), max_tokens=9000)
    pkg.stories = [_mk(Story, s) for s in data.get("stories") or []]
    for s in pkg.stories:
        # Без файла историй ничего не может быть «рассказом кандидата»: модель
        # иногда помечает так кейсы, выведенные из резюме (живая проверка 21.09).
        if not filled or not s.origin:
            s.origin = "рассказ кандидата" if filled and s.origin else "каркас из резюме"


def _stage_agenda(pkg, api_key, vac, title, company, resume, facts) -> None:
    kb_agenda = kb.agenda_rules()
    common = "\n".join(f"- {x}" for x, _s in kb.dont_say_checklist())
    data = _call_llm(api_key, _AGENDA_SYSTEM, _AGENDA_USER.format(
        title=title, company=company, vacancy_text=vac,
        resume_text=resume, facts=facts,
        risks="; ".join(pkg.top_risks) or "—",
        kb_agenda=kb_agenda, dont_say_common=common,
    ), max_tokens=6000)
    pkg.agenda = [
        AgendaItem(topic=a.get("topic", ""), thesis=a.get("thesis", ""), case=a.get("case", ""),
                   sources=_clean_sources(a.get("sources"), kb_agenda,
                                          ["real_stories.md — A3 «Повестка CIO 2026»",
                                           "executive_search.md — п. 7"]))
        for a in data.get("agenda") or []
    ]
    pkg.blitz = [_mk(BlitzQA, b) for b in data.get("blitz") or []]
    pkg.dont_say = [
        DontSayItem(text=d.get("text", ""), source=d.get("why", ""), personal=True)
        for d in data.get("dont_say_personal") or [] if d.get("text")
    ]
    pkg.key_numbers = [str(x) for x in data.get("key_numbers") or []][:5]


_BASIS = ("вакансия", "компания", "отрасль")


def _stage_improve(pkg, api_key, vac, title, company, resume, facts) -> None:
    kb_impr = kb.improve_rules() or "— база знаний недоступна —"
    data = _call_llm(api_key, _IMPR_SYSTEM, _IMPR_USER.format(
        title=title, company=company, vacancy_text=vac,
        resume_text=resume, facts=facts,
        trumps="; ".join(pkg.top_trumps) or "—",
        hundred_pitch=pkg.hundred_days.pitch or "—",
        kb_improve=kb_impr,
    ), max_tokens=6000)
    items = []
    for raw in data.get("items") or []:
        it = _mk(Improvement, raw)
        low = it.basis.lower()
        found = [(low.find(b), b) for b in _BASIS if b in low]
        it.basis = min(found)[1] if found else low.strip()   # первое из известных слов
        if it.area or it.hypothesis:
            items.append(it)
    pkg.improvements = Improvements(
        frame=data.get("frame", ""), context=data.get("context", ""),
        trends=[str(t) for t in data.get("trends") or []][:6],
        items=items[:6],
        sources=_clean_sources(data.get("sources"), kb_impr,
                               ["employers_official.md — п. 5, 6 (Газпром нефть, Билайн, НЛМК)",
                                "real_stories.md — «Банк кейсов и домашних заданий» (S5, S12, S16)",
                                "executive_search.md — п. 2.2"]),
    )


def load_stories(path: Path | None = None) -> str:
    """
    Личный файл историй кандидата (вне git). Возвращает содержимое без
    заголовков и подсказок (строки «>»); пустая строка — если файла нет или он
    содержит только шаблон.
    """
    path = path or STORIES_PATH
    if not path.exists():
        return ""
    raw = path.read_text(encoding="utf-8")
    meaningful = [
        ln for ln in raw.splitlines()
        if ln.strip() and not ln.lstrip().startswith(("#", ">"))
    ]
    if len(" ".join(meaningful).strip()) < 40:
        return ""
    return raw


STORIES_TEMPLATE = """\
# Истории для собеседований (личный файл, вне git)

> Назначение: сырьё для раздела «Истории и кейсы» в пакете подготовки.
> Пишите своими словами, без полировки — генератор сам приведёт к формату
> «задача → роль → решение → обоснование → результат в цифрах → вывод» и
> заточит под конкретную вакансию. Пока раздел пуст, пакет показывает каркасы
> историй из проектов резюме с вопросами, что нужно вспомнить.
>
> Правило то же, что в факт-базе: только то, что было на самом деле. Цифры
> будут проверять по референсам трёх уровней (real_stories S3, S4).
> Строки, начинающиеся с «>», и заголовки генератор не считает содержанием.

## Конфликт 1 — с первым лицом или собственником
> Пример темы: разошлись по стратегии, бюджету, срокам. Что стало предметом
> спора, как договаривались, чем закончилось, что изменили бы сегодня.

## Конфликт 2 — с командой или смежным подразделением
> Пример: директора заводов саботируют внедрение, вендор срывает сроки,
> сильный сотрудник против изменений, смежный блок тянет одеяло.

## Провальный проект
> Что не получилось, почему, что вы сделали как руководитель, какой урок
> вынесли. Честный разбор считается признаком зрелости.

## Ошибка руководителя
> Личная управленческая ошибка: найм, делегирование, решение, которое
> пришлось откатить. Как заметили, как исправили.

## Изменённый процесс
> Процесс, который вы перестроили: как было, что сделали, эффект в цифрах.

## Управленческие кейсы (по желанию)
> Масштабирование · повышение эффективности · реструктуризация · антикризис.
> Если есть реальная история под сценарий — напишите здесь; иначе генератор
> построит каркас из проектов резюме.

### Масштабирование

### Повышение эффективности

### Реструктуризация

### Антикризисное управление
"""


def ensure_stories_template(path: Path | None = None) -> Path:
    """Создаёт шаблон файла историй, если файла ещё нет. Возвращает путь."""
    path = path or STORIES_PATH
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(STORIES_TEMPLATE.encode("utf-8"))
    return path


def load_saved_prep(package_id: str) -> PrepPackage | None:
    path = OUTPUT_DIR / f"{_safe_id(package_id)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _package_from_dict(data)
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None


def _package_from_dict(data: dict) -> PrepPackage:
    """Совместимо со старыми пакетами: недостающие поля получают значения по умолчанию."""
    d = dict(data)
    d["qa"] = [_mk(PrepQA, q) for q in d.get("qa") or []]
    d["hr_qa"] = [_mk(PrepQA, q) for q in d.get("hr_qa") or []]
    d["user_qa"] = [_mk(PrepQA, q) for q in d.get("user_qa") or []]
    d["employer_questions"] = [_mk(EmployerQuestion, q) for q in d.get("employer_questions") or []]
    d["purple_rounds"] = [_mk(PurpleRound, r) for r in d.get("purple_rounds") or []]
    p = d.get("process") or {}
    d["process"] = ProcessMap(**{**_only(ProcessMap, p),
                                 "stages": [_mk(ProcessStage, s) for s in p.get("stages") or []]})
    d["presentation"] = _mk(Presentation, d.get("presentation") or {})
    d["stories"] = [_mk(Story, s) for s in d.get("stories") or []]
    d["hundred_days"] = _mk(HundredDays, d.get("hundred_days") or {})
    d["agenda"] = [_mk(AgendaItem, a) for a in d.get("agenda") or []]
    d["blitz"] = [_mk(BlitzQA, b) for b in d.get("blitz") or []]
    d["dont_say"] = [_mk(DontSayItem, x) for x in d.get("dont_say") or []]
    im = d.get("improvements") or {}
    d["improvements"] = Improvements(**{**_only(Improvements, im),
                                        "items": [_mk(Improvement, x) for x in im.get("items") or []]})
    return PrepPackage(**_only(PrepPackage, d))


# ---------------------------------------------------------------------------
# Cheat sheet — «10 минут до звонка», без модели
# ---------------------------------------------------------------------------

@dataclass
class CheatSheet:
    title: str = ""
    company: str = ""
    url: str = ""
    presentation_short: str = ""
    scope_line: str = ""
    trumps: list[str] = field(default_factory=list)
    risk_answers: list[tuple[str, str]] = field(default_factory=list)  # (вопрос, отточенный ответ)
    key_numbers: list[str] = field(default_factory=list)
    employer_questions: list[str] = field(default_factory=list)
    dont_say: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    blitz: list[BlitzQA] = field(default_factory=list)
    hundred_days_pitch: str = ""
    improve: list[str] = field(default_factory=list)  # «что бы вы улучшили» — вслух
    generated_at: str = ""


def build_cheatsheet(pkg: PrepPackage) -> CheatSheet:
    cs = CheatSheet(
        title=pkg.vacancy_title, company=pkg.company, url=pkg.vacancy_url,
        presentation_short=pkg.presentation.short,
        scope_line=pkg.presentation.scope_line,
        trumps=list(pkg.top_trumps[:3]),
        key_numbers=list(pkg.key_numbers[:5]),
        employer_questions=[q.question for q in pkg.employer_questions[:3]],
        stages=[f"{s.stage} — {s.who}" + (f" · {s.duration}" if s.duration else "")
                for s in pkg.process.stages],
        blitz=list(pkg.blitz[:5]),
        hundred_days_pitch=pkg.hundred_days.pitch,
        improve=[i.phrasing or i.hypothesis for i in pkg.improvements.items
                 if i.phrasing or i.hypothesis][:3],
        generated_at=pkg.generated_at,
    )
    rounds = [(r.attack, r.improved_answer or r.defense) for r in pkg.purple_rounds if r.attack]
    if len(rounds) < 3:
        rounds += [(q.question, q.answer) for q in pkg.qa if q.severity == "risk"]
    cs.risk_answers = rounds[:3]
    personal = [d.text for d in pkg.dont_say if d.personal]
    common = [d.text for d in pkg.dont_say if not d.personal]
    cs.dont_say = (personal + common)[:6]
    return cs


# ---------------------------------------------------------------------------
# Ask-your-double
# ---------------------------------------------------------------------------

_ASK_SYSTEM = _LANG_RULES + """

Ты — AI-двойник кандидата на собеседовании. Пользователь (сам кандидат)
задаёт вопрос — так, как его мог бы задать интервьюер на этой вакансии.
Дай заготовку ответа ОТ ПЕРВОГО ЛИЦА кандидата: 2-5 предложений, плотно,
на фактах из резюме и факт-базы, без выдумки. Если фактов не хватает —
построй ответ через смежный опыт или честное признание границы, и скажи
об этом в поле note. Отвечай строго валидным JSON."""

_ASK_USER = """\
ВАКАНСИЯ: {title} · {company}
Профиль интервьюера: {interviewer_profile}

РЕЗЮМЕ КАНДИДАТА:
---
{resume_text}
---

ФАКТ-БАЗА:
---
{facts}
---

ВОПРОС ИНТЕРВЬЮЕРА (задан пользователем):
«{question}»

Верни ТОЛЬКО валидный JSON:
{{
  "answer": "заготовка ответа от первого лица",
  "note": "необязательное примечание: чем ответ подкреплён слабо / что уточнить у кандидата (или пустая строка)"
}}"""


def answer_user_question(package_id: str, question: str) -> PrepQA:
    """Answer a user-typed interviewer question and persist it in the package."""
    question = (question or "").strip()
    if not question:
        return PrepQA(question="", answer="", severity="user")

    pkg = load_saved_prep(package_id)
    api_key = _get_api_key()
    if not api_key:
        return PrepQA(question=question, answer="Нет ANTHROPIC_API_KEY.", severity="user")

    try:
        resume = load_canonical_resume()
    except Exception as exc:
        return PrepQA(question=question, answer=f"Не удалось прочитать резюме: {exc}", severity="user")

    data = _call_llm(api_key, _ASK_SYSTEM, _ASK_USER.format(
        title=pkg.vacancy_title if pkg else "—",
        company=pkg.company if pkg else "—",
        interviewer_profile=pkg.interviewer_profile if pkg else "—",
        resume_text=resume,
        facts=load_facts() or "— факт-база пуста —",
        question=question,
    ), max_tokens=2000)

    item = PrepQA(
        source=(data.get("note") or "ваш вопрос").strip() or "ваш вопрос",
        question=question,
        answer=data.get("answer", ""),
        severity="user",
    )
    if pkg is not None:
        pkg.user_qa.append(item)
        _save(pkg)
    return item


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _only(cls, d: dict) -> dict:
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in (d or {}).items() if k in names}


def _mk(cls, d: dict):
    """Экземпляр dataclass из словаря: лишние ключи отбрасываются, недостающие — по умолчанию."""
    return cls(**_only(cls, d if isinstance(d, dict) else {}))


def _static_sources(corpus: str, *defaults: str) -> list[str]:
    return list(defaults) if corpus and "недоступна" not in corpus[:40] else []


def _clean_sources(items, corpus: str, defaults: list[str] | None = None) -> list[str]:
    """
    Источники от модели: оставляем строки, хотя бы один значимый токен которых
    встречается в выдержке (защита от выдуманных ссылок); пустой результат
    заменяется источниками по умолчанию. Метки разворачиваются в названия.
    """
    kept: list[str] = []
    corpus = corpus or ""
    low = corpus.lower()
    for raw in items or []:
        s = str(raw).strip()
        if not s:
            continue
        tags = re.findall(r"\b(?:S\d{1,2}|A\d|Д\d{1,2}|М\d)\b", s)
        tokens = [
            t for t in re.findall(r"[a-zа-яё0-9][a-zа-яё0-9.\-]{2,}", s.lower())
            if t != "источник" and not re.fullmatch(r"[a-zа-я]?\d+", t)
        ]
        if (s.lower() in low
                or any(re.search(rf"\b{re.escape(t)}\b", corpus) for t in tags)
                or any(t in low for t in tokens)):
            kept.append(s)
    if not kept:
        kept = list(defaults or [])
    seen, out = set(), []
    for s in kept:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return kb.resolve_sources(out[:6])


def _safe_id(package_id: str) -> str:
    return re.sub(r"[^\w\-]", "_", package_id)


_KIND_TITLES = {
    "conflict_top": "Конфликт с первым лицом",
    "conflict_team": "Конфликт с командой или смежниками",
    "failure": "Провальный проект",
    "leader_mistake": "Ошибка руководителя",
    "process_change": "Изменённый процесс",
    "case_scaling": "Кейс: масштабирование",
    "case_efficiency": "Кейс: повышение эффективности",
    "case_restructuring": "Кейс: реструктуризация",
    "case_crisis": "Кейс: антикризисное управление",
}


def kind_title(kind: str) -> str:
    return _KIND_TITLES.get(kind, kind or "История")


def _src_line(sources: list[str]) -> list[str]:
    return [f"_Источники: {'; '.join(sources)}_", ""] if sources else []


def _save(pkg: PrepPackage) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sid = _safe_id(pkg.package_id)
    (OUTPUT_DIR / f"{sid}.json").write_text(
        json.dumps(asdict(pkg), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    md = [
        f"# Пакет подготовки: {pkg.vacancy_title}",
        "",
        f"_Компания: {pkg.company} · {pkg.vacancy_url}_",
        f"_Сгенерировано: {pkg.generated_at}"
        + (f" · база знаний от {pkg.kb_version}" if pkg.kb_version else "") + "_",
        "",
    ]
    if pkg.stage_errors:
        md += ["> Часть разделов не собралась: " + "; ".join(pkg.stage_errors), ""]

    if pkg.process.stages or pkg.process.company_note:
        md += ["## Как проходит процесс и кто передо мной", "", pkg.process.company_note, ""]
        if pkg.process.total:
            md += [f"**Итого:** {pkg.process.total}", ""]
        for i, s in enumerate(pkg.process.stages, 1):
            md += [f"### {i}. {s.stage} — {s.who}",
                   f"_{s.duration}_" if s.duration else "",
                   "", f"**Что проверяют:** {s.probes}", "", f"**Как готовиться:** {s.tip}", ""]
        md += _src_line(pkg.process.sources)

    md += ["## Кто вас будет спрашивать", "", pkg.interviewer_profile, "",
           "## Козыри под эту вакансию", ""]
    md += [f"- {t}" for t in pkg.top_trumps]
    md += ["", "## Болевые зоны", ""]
    md += [f"- {r}" for r in pkg.top_risks]
    md += [""]

    if pkg.presentation.short or pkg.presentation.long:
        md += ["## Самопрезентация", "",
               "### 1–3 минуты (скрининг)", "", pkg.presentation.short, "",
               "### 5–7 минут (финал, знакомство с командой)", "", pkg.presentation.long, ""]
        if pkg.presentation.scope_line:
            md += [f"**Руками / делегирую / контролирую:** {pkg.presentation.scope_line}", ""]
        md += _src_line(pkg.presentation.sources)

    md += ["## Вопросы интервьюера и заготовки ответов", ""]
    for i, q in enumerate(pkg.qa, 1):
        md += [f"### {i}. {q.question}", f"_Источник: {q.source} · зона: {q.severity}_", "", q.answer, ""]
    md += _src_line(pkg.qa_sources)
    md += ["## Общие и поведенческие вопросы (HR)", ""]
    for i, q in enumerate(pkg.hr_qa, 1):
        md += [f"### {i}. {q.question}", f"_Тема: {q.source}_", "", q.answer, ""]
    md += _src_line(pkg.hr_sources)

    if pkg.stories:
        md += ["## Истории и управленческие кейсы", "",
               f"_Основа: {pkg.stories_origin or '—'}_", ""]
        for s in pkg.stories:
            md += [f"### {kind_title(s.kind)}: {s.title}", f"_{s.origin}_", "",
                   f"**Ситуация.** {s.situation}", "", f"**Действия.** {s.actions}", "",
                   f"**Результат.** {s.result}", "", f"**Вывод.** {s.lesson}", ""]
            if s.gaps:
                md += [f"**Что вспомнить:** {s.gaps}", ""]

    if pkg.hundred_days.block1:
        md += ["## План первых 100 дней", "",
               f"**Дни 1–30.** {pkg.hundred_days.block1}", "",
               f"**Дни 31–60.** {pkg.hundred_days.block2}", "",
               f"**Дни 61–100.** {pkg.hundred_days.block3}", "",
               f"**Устно, за минуту:** {pkg.hundred_days.pitch}", ""]
        md += _src_line(pkg.hundred_days.sources)

    im = pkg.improvements
    if im.items or im.frame:
        md += ["## «Что бы вы улучшили у нас?»", ""]
        if im.frame:
            md += [f"**Как отвечать.** {im.frame}", ""]
        if im.context:
            md += [f"**Отрасль и компания.** {im.context}", ""]
        if im.trends:
            md += ["**Тренды под эту роль:**"] + [f"- {t}" for t in im.trends] + [""]
        for i, it in enumerate(im.items, 1):
            md += [f"### {i}. {it.area}" + (f" _({it.basis})_" if it.basis else ""), "",
                   f"**Сигнал.** {it.signal}", "", f"**Гипотеза.** {it.hypothesis}", "",
                   f"**Сказать вслух.** {it.phrasing}", "", f"**Проверить вопросом.** {it.check}", "",
                   f"**Опора в опыте.** {it.backing}", ""]
        md += _src_line(im.sources)

    if pkg.agenda:
        md += ["## Повестка 2026", ""]
        for a in pkg.agenda:
            md += [f"### {a.topic}", "", a.thesis, "", f"**Кейс:** {a.case}", ""]
            md += _src_line(a.sources)

    if pkg.blitz:
        md += ["## Блиц «экзамен»", ""]
        md += [f"- **{b.question}** — {b.answer}" for b in pkg.blitz]
        md += [""]

    if pkg.user_qa:
        md += ["## Ваши собственные вопросы (спрошено у двойника)", ""]
        for q in pkg.user_qa:
            md += [f"### {q.question}", "", q.answer, ""]
            if q.source and q.source != "ваш вопрос":
                md += [f"_Примечание: {q.source}_", ""]
    md += ["## Ваши вопросы работодателю", ""]
    for q in pkg.employer_questions:
        md += [f"- **{q.question}**", f"  _{q.why}_", ""]
    md += _src_line(pkg.employer_sources)
    md += ["## Purple Team — спарринг", ""]
    for i, r in enumerate(pkg.purple_rounds, 1):
        md += [f"### Раунд {i}", f"**🔴 Рекрутёр:** {r.attack}", "", f"**🔵 Вы:** {r.defense}", "",
               f"**⚖ Судья:** {r.verdict}", "", f"**Отточенный ответ:** {r.improved_answer}", ""]

    if pkg.dont_say:
        md += ["## Чего не говорить", ""]
        for d in pkg.dont_say:
            tag = "**Лично для вас.** " if d.personal else ""
            md += [f"- {tag}{d.text}" + (f" _({d.source})_" if d.source else "")]
        md += [""]

    if pkg.schema_version >= SCHEMA_VERSION:
        cs = build_cheatsheet(pkg)
        md += ["## Шпаргалка: 10 минут до звонка", ""]
        if cs.presentation_short:
            md += ["**О себе (1–3 мин):** " + cs.presentation_short, ""]
        if cs.trumps:
            md += ["**Козыри:** " + " · ".join(cs.trumps), ""]
        for q, a in cs.risk_answers:
            md += [f"**Если спросят:** {q}", f"→ {a}", ""]
        if cs.key_numbers:
            md += ["**Цифры:** " + " · ".join(cs.key_numbers), ""]
        if cs.employer_questions:
            md += ["**Спросить:** " + " · ".join(cs.employer_questions), ""]
        if cs.improve:
            md += ["**Если спросят «что бы вы улучшили»:** " + " · ".join(cs.improve), ""]
        if cs.dont_say:
            md += ["**Не говорить:** " + " · ".join(cs.dont_say), ""]
    (OUTPUT_DIR / f"{sid}.md").write_text("\n".join(md), encoding="utf-8")


def _call_llm(api_key: str, system: str, prompt: str, max_tokens: int = 4000) -> dict:
    """Thin wrapper over the shared gateway (kept for test monkeypatching)."""
    from core import llm
    return llm.call_json(system, prompt, max_tokens=max_tokens, api_key=api_key,
                         banned_substrings=[", а не "])


def _get_api_key() -> str:
    from core import llm
    return llm.get_api_key()
