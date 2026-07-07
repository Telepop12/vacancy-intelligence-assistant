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

Три LLM-этапа:
  1. Вопросы интервьюера + заготовки ответов (на фактах канона и факт-базы).
  2. Вопросы кандидата к работодателю (мандат, бюджет, ожидания 90 дней...).
  3. Purple Team: AI-рекрутёр атакует слабые места ↔ AI-двойник кандидата
     защищается, судья оценивает раунды и выдаёт отточенные формулировки.

Артефакты: output/prep/{id}.json / {id}.md.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from agents.resume_variants import load_canonical_resume, load_facts, load_variants_config

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output" / "prep"

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
class PrepPackage:
    package_id: str = ""
    vacancy_title: str = ""
    company: str = ""
    vacancy_url: str = ""
    interviewer_profile: str = ""   # «с чьих позиций» построены вопросы
    qa: list[PrepQA] = field(default_factory=list)
    employer_questions: list[EmployerQuestion] = field(default_factory=list)
    purple_rounds: list[PurpleRound] = field(default_factory=list)
    top_risks: list[str] = field(default_factory=list)
    top_trumps: list[str] = field(default_factory=list)   # козыри под эту вакансию
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
поплыл, а реально делавший — ответил конкретикой.

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
подать их сильно), и болевые зоны; вопросы к цифрам обязательны.
Ответы (answer) — плотные, 2-3 предложения, без воды."""


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

Верни ТОЛЬКО валидный JSON:
{{
  "employer_questions": [
    {{"question": "вопрос работодателю", "why": "что вопрос даёт кандидату и как звучит для нанимающего"}}
  ]
}}
6-8 вопросов: мандат и полномочия роли, бюджет, ожидания на 90 дней,
что случилось с предшественником, критерии успеха через год, команда,
реальная поддержка изменений первым лицом — выбирай релевантное вакансии."""


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
) -> PrepPackage:
    """Generate the full interview prep package for one vacancy."""
    pkg = PrepPackage(
        package_id=package_id or datetime.now().strftime("prep_%Y%m%d_%H%M%S"),
        vacancy_title=title,
        company=company,
        vacancy_url=url,
        generated_at=datetime.now().isoformat(timespec="seconds"),
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

    try:
        # Stage 1 — interviewer QA
        data = _call_llm(api_key, _QA_SYSTEM, _QA_USER.format(
            vacancy_text=vac, title=title or "—", company=company or "—",
            resume_text=resume, facts=facts,
        ), max_tokens=6000)
        pkg.interviewer_profile = data.get("interviewer_profile", "")
        pkg.qa = [PrepQA(**{k: q.get(k, "") for k in ("source", "question", "answer", "severity")})
                  for q in data.get("qa") or []]
        pkg.top_risks = data.get("top_risks") or []
        pkg.top_trumps = data.get("top_trumps") or []

        # Stage 2 — employer questions
        brief = f"{title}; козыри: {'; '.join(pkg.top_trumps[:3])}; риски: {'; '.join(pkg.top_risks[:3])}"
        data2 = _call_llm(api_key, _EMP_SYSTEM, _EMP_USER.format(
            vacancy_text=vac, candidate_brief=brief,
        ), max_tokens=2500)
        pkg.employer_questions = [
            EmployerQuestion(question=q.get("question", ""), why=q.get("why", ""))
            for q in data2.get("employer_questions") or []
        ]

        # Stage 3 — Purple Team
        data3 = _call_llm(api_key, _PURPLE_SYSTEM, _PURPLE_USER.format(
            title=title or "—", company=company or "—",
            interviewer_profile=pkg.interviewer_profile,
            risks="; ".join(pkg.top_risks) or "по рискам из резюме",
            resume_text=resume, facts=facts, rounds=purple_rounds,
        ), max_tokens=4000)
        pkg.purple_rounds = [
            PurpleRound(**{k: r.get(k, "") for k in ("attack", "defense", "verdict", "improved_answer")})
            for r in data3.get("purple_rounds") or []
        ]

        if not pkg.qa:
            pkg.error = "LLM вернул пустой список вопросов — повторите генерацию"
            return pkg
        _save(pkg)
    except Exception as exc:
        pkg.error = f"Ошибка генерации: {exc}"

    return pkg


def load_saved_prep(package_id: str) -> PrepPackage | None:
    path = OUTPUT_DIR / f"{_safe_id(package_id)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["qa"] = [PrepQA(**q) for q in data.get("qa", [])]
        data["employer_questions"] = [EmployerQuestion(**q) for q in data.get("employer_questions", [])]
        data["purple_rounds"] = [PurpleRound(**r) for r in data.get("purple_rounds", [])]
        return PrepPackage(**data)
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _safe_id(package_id: str) -> str:
    return re.sub(r"[^\w\-]", "_", package_id)


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
        f"_Сгенерировано: {pkg.generated_at}_",
        "",
        "## Кто вас будет спрашивать",
        "",
        pkg.interviewer_profile,
        "",
        "## Козыри под эту вакансию",
        "",
    ]
    md += [f"- {t}" for t in pkg.top_trumps]
    md += ["", "## Болевые зоны", ""]
    md += [f"- {r}" for r in pkg.top_risks]
    md += ["", "## Вопросы интервьюера и заготовки ответов", ""]
    for i, q in enumerate(pkg.qa, 1):
        md += [
            f"### {i}. {q.question}",
            f"_Источник: {q.source} · зона: {q.severity}_",
            "",
            q.answer,
            "",
        ]
    md += ["## Ваши вопросы работодателю", ""]
    for q in pkg.employer_questions:
        md += [f"- **{q.question}**", f"  _{q.why}_", ""]
    md += ["## Purple Team — спарринг", ""]
    for i, r in enumerate(pkg.purple_rounds, 1):
        md += [
            f"### Раунд {i}",
            f"**🔴 Рекрутёр:** {r.attack}",
            "",
            f"**🔵 Вы:** {r.defense}",
            "",
            f"**⚖ Судья:** {r.verdict}",
            "",
            f"**Отточенный ответ:** {r.improved_answer}",
            "",
        ]
    (OUTPUT_DIR / f"{sid}.md").write_text("\n".join(md), encoding="utf-8")


def _call_llm(api_key: str, system: str, prompt: str, max_tokens: int = 4000) -> dict:
    """LLM call with JSON parsing; retries once on truncation/invalid JSON."""
    import anthropic
    import httpx

    client = anthropic.Anthropic(api_key=api_key, http_client=httpx.Client(trust_env=False))
    attempt_prompt, attempt_tokens = prompt, max_tokens
    last_err: Exception | None = None
    for _ in range(2):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=attempt_tokens,
            system=system,
            messages=[{"role": "user", "content": attempt_prompt}],
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
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            last_err = exc
            # Truncated by the token limit or malformed — one denser retry
            attempt_tokens = min(int(attempt_tokens * 1.6), 16000)
            attempt_prompt = prompt + (
                "\n\nВАЖНО: прошлый ответ оборвался или содержал невалидный JSON. "
                "Сократи формулировки (ответы по 2-3 предложения) и верни "
                "СТРОГО валидный JSON целиком."
            )
    raise last_err  # type: ignore[misc]


def _get_api_key() -> str:
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key if key and not key.startswith("sk-ant-ВАШ") else ""
