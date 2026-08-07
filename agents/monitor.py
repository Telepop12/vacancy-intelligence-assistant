"""
Мониторинг новых вакансий с алертом в Telegram.

Идея (из ресёрча рынка): скорость отклика влияет на видимость у рекрутёра —
но автоотклик запрещён правилами hh и этически неприемлем. Наш вариант:
система регулярно ищет новое, СРАЗУ готовит пакет отклика для сильных
вакансий и присылает алерт — человеку остаётся прочитать письмо и нажать
«Откликнуться» под своей сессией hh. Мгновенная реакция, кнопка — за человеком.

Цикл (run_cycle):
  1. run_search() — обычный автопоиск (кеш, вежливые паузы, всё как всегда);
  2. новые вакансии с score >= порога → дайджест (output/monitor_digest.json);
  3. для топ-N из них автогенерация пакета отклика (письмо + скринер);
  4. Telegram-сводка, если настроен TG_BOT_TOKEN (chat_id определяется
     автоматически по первому сообщению пользователя боту).

Шедулер — фоновый поток в веб-приложении (web/app.py), интервал и порог —
config/monitor.yaml.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "monitor.yaml"
DIGEST_PATH = BASE_DIR / "output" / "monitor_digest.json"
TG_STATE_PATH = BASE_DIR / "output" / "tg_state.json"

log = logging.getLogger("monitor")

DEFAULT_CONFIG = {
    "enabled": True,
    "interval_hours": 6,
    "score_threshold": 60,
    "max_packages_per_cycle": 3,
    "lookback_hours": 48,   # какой давности триаж ещё считается «новым»
}


def load_monitor_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            user_cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            cfg.update({k: v for k, v in user_cfg.items() if v is not None})
        except yaml.YAMLError:
            pass
    return cfg


@dataclass
class DigestEntry:
    vid: str
    title: str = ""
    company: str = ""
    score: int = 0
    recommendation: str = ""
    found_at: str = ""
    package_ready: bool = False
    notified: bool = False


@dataclass
class CycleResult:
    started_at: str = ""
    found_total: int = 0        # всего вакансий в выдаче по запросам
    new_total: int = 0          # из них новых (оценены в этом цикле)
    new_strong: int = 0         # из новых — выше порога
    packages_built: int = 0
    notified: bool = False
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Digest storage
# ---------------------------------------------------------------------------

def load_digest() -> list[dict]:
    if not DIGEST_PATH.exists():
        return []
    try:
        return json.loads(DIGEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_digest(entries: list[dict]) -> None:
    DIGEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIGEST_PATH.write_text(
        json.dumps(entries[-200:], ensure_ascii=False, indent=1), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Telegram (stdlib only; безопасно молчит, если токен не настроен)
# ---------------------------------------------------------------------------

def _tg_token() -> str:
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
    return os.environ.get("TG_BOT_TOKEN", "").strip()


def _tg_api(token: str, method: str, params: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    with urllib.request.urlopen(url, data=data, timeout=20) as resp:
        return json.loads(resp.read())


def _tg_chat_id(token: str) -> str:
    """Cached chat_id; discovered from the first message the user sends the bot."""
    if TG_STATE_PATH.exists():
        try:
            state = json.loads(TG_STATE_PATH.read_text(encoding="utf-8"))
            if state.get("chat_id"):
                return str(state["chat_id"])
        except (json.JSONDecodeError, OSError):
            pass
    try:
        updates = _tg_api(token, "getUpdates")
        for upd in reversed(updates.get("result", [])):
            chat = (upd.get("message") or {}).get("chat") or {}
            if chat.get("id"):
                TG_STATE_PATH.write_text(
                    json.dumps({"chat_id": chat["id"]}), encoding="utf-8"
                )
                return str(chat["id"])
    except Exception:
        pass
    return ""


def send_telegram(text: str) -> bool:
    """Send an alert; returns False (silently) when TG is not configured."""
    token = _tg_token()
    if not token:
        return False
    chat_id = _tg_chat_id(token)
    if not chat_id:
        return False
    try:
        _tg_api(token, "sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        })
        return True
    except Exception:
        return False


def telegram_status() -> str:
    """For the UI: 'off' | 'waiting_chat' | 'ready'."""
    token = _tg_token()
    if not token:
        return "off"
    return "ready" if _tg_chat_id(token) else "waiting_chat"


# ---------------------------------------------------------------------------
# The cycle
# ---------------------------------------------------------------------------

def run_cycle(profile, base_url: str = "http://localhost:8000") -> CycleResult:
    from agents import vacancy_store
    from agents.application_package import build_package, load_saved_package
    from agents.hh_search import run_search

    cfg = load_monitor_config()
    result = CycleResult(started_at=datetime.now().isoformat(timespec="seconds"))

    digest = load_digest()
    known = {e["vid"] for e in digest}

    # 1. Обычный автопоиск (переиспользуем весь конвейер как есть)
    try:
        search = run_search(profile)
    except Exception as exc:
        log.exception("Цикл мониторинга: поиск упал")
        result.errors.append(f"Поиск: {exc}")
        return result
    result.errors.extend(search.errors[:3])

    # 2. Новые сильные вакансии — свежетриажированные (в т.ч. ручным поиском
    #    со страницы /search в пределах lookback_hours) и не встречавшиеся
    #    в дайджесте. Жёсткое «только сегодня» теряло находки: вакансия 82
    #    балла, найденная ручным поиском 06.08, не попала бы в цикл 07.08.
    cutoff = (
        datetime.now() - timedelta(hours=float(cfg.get("lookback_hours", 48)))
    ).isoformat(timespec="seconds")
    fresh = [
        it for it in search.items
        if not it.error and it.hh_id not in known
        and it.triaged_at and it.triaged_at >= cutoff
    ]
    result.found_total = search.found_total
    result.new_total = search.new_count
    strong = sorted(
        [it for it in fresh if it.score >= int(cfg["score_threshold"])],
        key=lambda it: -it.score,
    )
    result.new_strong = len(strong)
    if not strong:
        log.info(
            "Цикл мониторинга: найдено %s, новых %s, сильных нет — тихий цикл",
            result.found_total, result.new_total,
        )
        return result

    # 3. Автопакеты для топ-N
    max_pkg = int(cfg["max_packages_per_cycle"])
    for it in strong:
        entry = DigestEntry(
            vid=it.hh_id, title=it.title, company=it.company,
            score=it.score, recommendation=it.recommendation,
            found_at=result.started_at,
        )
        if result.packages_built < max_pkg and load_saved_package(f"hh_{it.hh_id}") is None:
            try:
                data = vacancy_store.resolve_vacancy(it.hh_id)
                pkg = build_package(
                    vacancy_text=data.get("description", ""),
                    title=data.get("name", ""), company=data.get("employer", ""),
                    url=data.get("alternate_url", ""), package_id=f"hh_{it.hh_id}",
                )
                entry.package_ready = not pkg.error
                if entry.package_ready:
                    result.packages_built += 1
            except Exception as exc:
                log.exception("Цикл мониторинга: не собрался пакет %s", it.hh_id)
                result.errors.append(f"Пакет {it.hh_id}: {exc}")
        digest.append(asdict(entry))

    # 4. Telegram-сводка
    lines = [f"🔍 <b>Новые вакансии: {result.new_strong}</b>"]
    for it in strong[:5]:
        ready = " · 📨 пакет готов" if any(
            e["vid"] == it.hh_id and e.get("package_ready") for e in digest
        ) else ""
        lines.append(
            f"• <b>{it.score}</b> — {it.title} ({it.company}){ready}\n"
            f"  {base_url}/vacancy/{it.hh_id}"
        )
    result.notified = send_telegram("\n".join(lines))
    if result.notified:
        for e in digest:
            if any(it.hh_id == e["vid"] for it in strong):
                e["notified"] = True

    _save_digest(digest)
    log.info(
        "Цикл мониторинга: найдено %s, новых %s, сильных %s, пакетов %s, алерт %s%s",
        result.found_total, result.new_total, result.new_strong,
        result.packages_built, "да" if result.notified else "нет",
        f", ошибки: {result.errors}" if result.errors else "",
    )
    return result
