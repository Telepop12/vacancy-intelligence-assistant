"""
Единый LLM-шлюз для всех агентов и анализаторов.

До рефакторинга клиент Anthropic, чтение ключа, парсинг JSON и ретраи были
скопированы в пяти модулях (claude_analyzer, career_match, resume_variants,
application_package, interview_prep) и понемногу расходились. Теперь всё
здесь; модели задаются в config/llm.yaml (примонтирован в контейнер —
смена модели не требует пересборки).

Гарантии call_json():
  - ответ парсится как JSON (срезаются ```-заборы и обрамляющий текст);
  - при невалидном/оборванном JSON — один повтор с просьбой ужаться и
    с увеличенным лимитом токенов (лечит обрыв по max_tokens);
  - опционально banned_substrings: если запрещённый оборот попал в ответ —
    один повтор с прямым указанием переписать (стайл-гвард «X, а не Y»).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "llm.yaml"

_DEFAULTS = {
    "model": "claude-sonnet-5",
    "effort": "medium",        # у Sonnet 5 medium ≈ high у Sonnet 4.6, дешевле
    "min_max_tokens": 6000,    # Sonnet 5 думает в счёт max_tokens + токенизатор ~+30%
    "max_json_retries": 1,
}


def load_llm_config() -> dict:
    cfg = dict(_DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            user_cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            cfg.update({k: v for k, v in user_cfg.items() if v is not None})
        except yaml.YAMLError:
            pass
    return cfg


def get_api_key() -> str:
    """ANTHROPIC_API_KEY из окружения или .env проекта; '' если не настроен."""
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return key if key and not key.startswith("sk-ant-ВАШ") else ""


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:])
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")].rstrip()
    start, end = raw.find("{"), raw.rfind("}") + 1
    if start >= 0 and end > start:
        raw = raw[start:end]
    return json.loads(raw)


def call_json(
    system: str,
    prompt: str,
    *,
    max_tokens: int = 4000,
    api_key: str | None = None,
    model: str | None = None,
    banned_substrings: list[str] | None = None,
) -> dict:
    """One LLM call returning parsed JSON, with truncation and style retries."""
    import anthropic
    import httpx

    cfg = load_llm_config()
    key = api_key or get_api_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY не настроен")
    client = anthropic.Anthropic(api_key=key, http_client=httpx.Client(trust_env=False))
    use_model = model or cfg["model"]

    # Sonnet 5+: адаптивное мышление включено по умолчанию и расходует
    # max_tokens вместе с текстом ответа — держим запас, чтобы не обрезало.
    max_tokens = max(max_tokens, int(cfg.get("min_max_tokens", 0)))
    extra: dict = {}
    if cfg.get("effort"):
        extra["output_config"] = {"effort": cfg["effort"]}

    attempt_prompt, attempt_tokens = prompt, max_tokens
    last_err: Exception | None = None
    data: dict | None = None

    for _ in range(1 + int(cfg.get("max_json_retries", 1))):
        response = client.messages.create(
            model=use_model,
            max_tokens=attempt_tokens,
            system=system,
            messages=[{"role": "user", "content": attempt_prompt}],
            **extra,
        )
        # Sonnet 5+: первым блоком приходит thinking — берём первый текстовый
        raw_text = next(
            (b.text for b in response.content if getattr(b, "type", "") == "text"), ""
        )
        try:
            data = _extract_json(raw_text)
            break
        except json.JSONDecodeError as exc:
            last_err = exc
            attempt_tokens = min(int(attempt_tokens * 1.6), 16000)
            attempt_prompt = prompt + (
                "\n\nВАЖНО: прошлый ответ оборвался или содержал невалидный JSON. "
                "Сократи формулировки и верни СТРОГО валидный JSON целиком."
            )
    if data is None:
        raise last_err  # type: ignore[misc]

    if banned_substrings:
        blob = json.dumps(data, ensure_ascii=False)
        hits = [b for b in banned_substrings if b in blob]
        if hits:
            listed = "; ".join(f"«{h}»" for h in hits)
            response = client.messages.create(
                model=use_model,
                max_tokens=attempt_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt + (
                    f"\n\nВАЖНО: в прошлой попытке встретились запрещённые "
                    f"обороты: {listed}. Перепиши формулировки без них и верни "
                    "СТРОГО валидный JSON."
                )}],
                **extra,
            )
            retry_text = next(
                (b.text for b in response.content if getattr(b, "type", "") == "text"), ""
            )
            try:
                data = _extract_json(retry_text)
            except json.JSONDecodeError:
                pass  # keep the first valid answer rather than fail
    return data
