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
class ApplicationPackage:
    package_id: str = ""            # hh_id или slug по времени
    vacancy_title: str = ""
    company: str = ""
    vacancy_url: str = ""
    letter: str = ""
    recommended_variant: str = ""   # ключ варианта (cio/cto/cdto/caio/universal)
    variant_name: str = ""
    variant_reasoning: str = ""
    hooks: list[str] = field(default_factory=list)  # какие требования вакансии зеркалим
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

Ты — консультант по executive-трудоустройству. Пишешь сопроводительные письма
для кандидата уровня CIO/CTO/CDTO/CAIO и выбираешь, какой из его постоянных
вариантов резюме лучше подходит под вакансию.

ЖЕЛЕЗНОЕ ПРАВИЛО — НИКАКОЙ ВЫДУМКИ:
- только факты из переданного резюме и факт-базы (компании, цифры, проекты);
- цифры точно как в источнике; факты со статусом «в работе» или «внутреннее»
  из факт-базы использовать НЕЛЬЗЯ — только со статусом ✅ или из резюме;
- если требование вакансии нечем закрыть — не выдумывай, выбери другое.

ТРЕБОВАНИЯ К ПИСЬМУ (спецификация заказчика, соблюдать строго):
- объём 120–150 слов (это ~половина экрана; длинные письма не читают);
- структура из трёх частей БЕЗ заголовков, плавным текстом:
  1) «обо мне» — 1–2 предложения, позиционирование под ЭТУ вакансию;
     первая строка — зацепка под конкретную задачу/боль из текста вакансии,
     не общие слова;
  2) «почему я» — 2–3 коротких буллета с конкретными цифрами и фактами,
     зеркалящими главные требования вакансии;
  3) заключение — конкретный следующий шаг (готов к короткому звонку/встрече),
     без подобострастия; подпись: имя, телефон, email (из резюме).
- язык вакансии: используй её ключевые термины, если они подтверждены опытом;
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

    vcfg = load_variants_config()["variants"]
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
        pkg.letter = (data.get("letter") or "").strip()
        pkg.recommended_variant = data.get("recommended_variant", "")
        pkg.variant_name = vcfg.get(pkg.recommended_variant, {}).get("name", pkg.recommended_variant)
        pkg.variant_reasoning = data.get("variant_reasoning", "")
        pkg.hooks = data.get("hooks") or []
        if not pkg.letter:
            pkg.error = "LLM вернул пустое письмо — повторите генерацию"
            return pkg
        _save_package(pkg)
    except Exception as exc:
        pkg.error = f"Ошибка генерации: {exc}"

    return pkg


def load_saved_package(package_id: str) -> ApplicationPackage | None:
    path = OUTPUT_DIR / f"{_safe_id(package_id)}.json"
    if not path.exists():
        return None
    try:
        return ApplicationPackage(**json.loads(path.read_text(encoding="utf-8")))
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
    (OUTPUT_DIR / f"{sid}.md").write_text("\n".join(md), encoding="utf-8")


def _call_llm(api_key: str, prompt: str) -> dict:
    import anthropic
    import httpx

    client = anthropic.Anthropic(api_key=api_key, http_client=httpx.Client(trust_env=False))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2500,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
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
    return json.loads(raw)


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
