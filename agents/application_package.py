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
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from agents.resume_variants import load_facts

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output" / "applications"


@dataclass
class ScreenerQA:
    question: str = ""
    answer: str = ""
    value_added: str = ""   # что в ответе есть СВЕРХ резюме (источник факта)


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
    screener_qa: list[ScreenerQA] = field(default_factory=list)  # диалог с ИИ-скринером hh
    generated_at: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# LLM prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Отвечай исключительно на деловом русском языке, живо и без канцелярита.
Допустимые термины: AI, ERP, MLOps, ROI, P&L, KPI, CEO, CIO, CTO, CDTO, CAIO,
M&A, BI, MES, ITSM, DevOps. Запрещены ИИ-штампы и пустые формулы:
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
- если требование вакансии нечем закрыть — не выдумывай, выбери другое.

ТРЕБОВАНИЯ К ПИСЬМУ (спецификация заказчика, соблюдать строго):
- объём СТРОГО 120–150 слов, не больше (длинные письма не читают);
  перед выдачей ответа пересчитай слова в письме; если вышло больше 150 —
  сократи буллеты и повтори проверку;
- структура из трёх частей БЕЗ заголовков, плавным текстом:
  1) «обо мне» — открытие нейтральное и вежливое, ДВА отдельных
     предложения без склейки через тире:
     первое — короткое: «Заинтересовала ваша вакансия [название].» И ВСЁ,
     без продолжения в том же предложении;
     второе — мягкая связка: мой опыт [краткая суть: чем руководил,
     масштаб] соответствует вашим требованиям и поможет [конкретная
     польза для компании, взятая из задач вакансии: улучшить/выстроить/
     масштабировать …]. Тон — спокойный и уверенный, не «продающий».
     НЕ пересказывай компании её вакансию («Вы ищете…», «Вам нужен…» —
     запрещено). НЕ используй конструкцию «именно такие задачи я решал»
     в первом абзаце;
  2) «почему я» — 2–3 коротких буллета с конкретными цифрами и фактами,
     зеркалящими главные требования вакансии;
  3) заключение — конкретный следующий шаг (готов к короткому звонку/встрече),
     без подобострастия; подпись: имя, телефон, email (из резюме).
- язык вакансии: используй её ключевые термины, если они подтверждены опытом;
- ЧИТАТЕЛЬ — HR, НЕ ТЕХНАРЬ (правило заказчика 2026-08-07): после
  ИИ-скрининга письмо читает живой рекрутёр без технического бэкграунда.
  Узкоспециальные термины либо не использовать, либо давать с пояснением
  в 2-3 слова: «предиктивная диагностика (предсказание поломок
  оборудования)». Аббревиатуры за пределами разрешённого списка выше —
  только если они есть в тексте самой вакансии. Названия внутренних
  решений переводи в понятную пользу: не «AI-SOC, RAG-ассистенты», а
  «AI-решения для информационной безопасности, эксплуатации ИТ и
  бизнес-показателей»;
- обращение: «Добрый день!» без имени, если имя контакта неизвестно.

Отвечай строго валидным JSON без markdown вокруг."""

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

ПОСТОЯННЫЕ ВАРИАНТЫ РЕЗЮМЕ КАНДИДАТА НА HH (выбери ОДИН лучший под вакансию):
{variants_list}

Верни ТОЛЬКО валидный JSON:
{{
  "letter": "полный текст письма с переносами строк \\n, включая буллеты и подпись",
  "recommended_variant": "ключ варианта из списка",
  "variant_reasoning": "1-2 предложения: почему этот вариант под эту вакансию",
  "hooks": ["какое требование вакансии закрыто каким фактом — 2-4 пункта"]
}}"""


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
    """Generate a cover letter + resume-variant recommendation for one vacancy."""
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
        pkg.letter = (data.get("letter") or "").strip()
        pkg.recommended_variant = data.get("recommended_variant", "")
        rec_cfg = vcfg.get(pkg.recommended_variant, {})
        pkg.variant_name = rec_cfg.get("name", pkg.recommended_variant)
        pkg.variant_hh_url = rec_cfg.get("hh_url", "") or ""
        pkg.variant_reasoning = data.get("variant_reasoning", "")
        pkg.hooks = data.get("hooks") or []
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
        return ApplicationPackage(**data)
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
        "## Сопроводительное письмо",
        "",
        pkg.letter,
        "",
        "## Что зеркалим из вакансии",
        "",
    ]
    md += [f"- {h}" for h in pkg.hooks]
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
