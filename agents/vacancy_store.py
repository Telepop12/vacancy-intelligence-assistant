"""
Vacancy Store — единое хранилище вакансий для всего конвейера.

Зачем:
  1. Ручной ввод: не все вакансии парсятся с hh.ru (анти-бот, архив,
     другие площадки) — пользователь добавляет вакансию ссылкой или
     текстом, и она становится полноценной вакансией системы со скорингом
     и кнопками (Полный анализ / Пакет отклика / Подготовка).
  2. Кеш hh.ru: однажды загруженная вакансия сохраняется и больше не
     дёргает hh (меньше поводов для анти-бота).

Формат записи — intake-словарь того же вида, что отдаёт hh_api:
{name, employer, area, salary, alternate_url, published_at, hh_id, description}.

ID: числовой (vid == hh id) или ручной 'm<timestamp>'.
Файлы: output/vacancies/{vid}.json (git-ignored вместе со всем output).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORE_DIR = BASE_DIR / "output" / "vacancies"

_HH_URL_RE = re.compile(r"hh\.ru/vacancy/(\d+)")


def hh_id_from_url(url: str) -> str | None:
    m = _HH_URL_RE.search(url or "")
    return m.group(1) if m else None


def new_manual_id() -> str:
    return datetime.now().strftime("m%Y%m%d%H%M%S")


def _path(vid: str) -> Path:
    safe = re.sub(r"[^\w\-]", "_", str(vid))
    return STORE_DIR / f"{safe}.json"


def save_vacancy(data: dict, vid: str | None = None) -> str:
    vid = str(vid or data.get("hh_id") or new_manual_id())
    data = dict(data)
    data.setdefault("hh_id", vid)
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    _path(vid).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return vid


def load_vacancy(vid: str) -> dict | None:
    path = _path(vid)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def resolve_vacancy(vid: str) -> dict:
    """
    Store first; for numeric ids fall back to a live hh.ru fetch (and cache).
    Raises hh_api.HHApiError when the vacancy is unknown and can't be fetched.
    """
    data = load_vacancy(vid)
    if data is not None:
        return data

    from agents import hh_api
    if not str(vid).isdigit():
        raise hh_api.HHApiError(
            f"Вакансия {vid} не найдена в базе — добавьте её заново текстом"
        )
    data = hh_api.fetch_vacancy_data(vid)
    save_vacancy(data, vid)
    return data


# ---------------------------------------------------------------------------
# Favorites — survive any rescan/state wipe (separate file + cached vacancy)
# ---------------------------------------------------------------------------

FAV_PATH = BASE_DIR / "output" / "favorites.json"


def list_favorites() -> list[str]:
    if not FAV_PATH.exists():
        return []
    try:
        data = json.loads(FAV_PATH.read_text(encoding="utf-8"))
        return [str(v) for v in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_favorites(vids: list[str]) -> None:
    FAV_PATH.parent.mkdir(parents=True, exist_ok=True)
    FAV_PATH.write_text(json.dumps(vids, ensure_ascii=False), encoding="utf-8")


def is_favorite(vid: str) -> bool:
    return str(vid) in list_favorites()


def add_favorite(vid: str) -> None:
    vids = list_favorites()
    if str(vid) not in vids:
        vids.append(str(vid))
        _save_favorites(vids)


def remove_favorite(vid: str) -> None:
    vids = [v for v in list_favorites() if v != str(vid)]
    _save_favorites(vids)


def delete_vacancy(vid: str) -> None:
    """Remove a vacancy everywhere: favorites + cached data (state — caller's)."""
    remove_favorite(vid)
    undismiss(vid)
    _path(vid).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Dismissed («Пропустить») — вакансия остаётся в состоянии поиска (иначе
# автопоиск найдёт и загрузит её заново), но исчезает из лент и таблиц.
# Отдельный файл, как избранное: переживает пересканы.
# ---------------------------------------------------------------------------

DISMISSED_PATH = BASE_DIR / "output" / "dismissed.json"


def list_dismissed() -> list[str]:
    if not DISMISSED_PATH.exists():
        return []
    try:
        data = json.loads(DISMISSED_PATH.read_text(encoding="utf-8"))
        return [str(v) for v in data] if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_dismissed(vids: list[str]) -> None:
    DISMISSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    DISMISSED_PATH.write_text(json.dumps(vids, ensure_ascii=False), encoding="utf-8")


def is_dismissed(vid: str) -> bool:
    return str(vid) in list_dismissed()


def dismiss(vid: str) -> None:
    vids = list_dismissed()
    if str(vid) not in vids:
        vids.append(str(vid))
        _save_dismissed(vids)
    remove_favorite(vid)  # пропущенная не может быть избранной


def undismiss(vid: str) -> None:
    vids = [v for v in list_dismissed() if v != str(vid)]
    _save_dismissed(vids)


def manual_vacancy_dict(
    text: str, title: str = "", company: str = "", url: str = "",
) -> dict:
    """Build an intake dict from manually pasted vacancy description."""
    clean = (text or "").strip()
    first_line = clean.splitlines()[0].strip() if clean else ""
    return {
        "name": (title or first_line[:120] or "Вакансия (ручной ввод)").strip(),
        "employer": (company or "").strip(),
        "area": "",
        "salary": None,
        "alternate_url": (url or "").strip(),
        "published_at": datetime.now().strftime("%Y-%m-%d"),
        "hh_id": "",
        "description": clean,
    }
