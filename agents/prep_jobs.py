"""
Фоновая сборка пакета подготовки к интервью (BACKLOG 6a, 22.09.2026).

Полная сборка — восемь вызовов модели, 10–25 минут; держать всё это время
открытый HTTP-запрос нельзя (браузер и прокси рвут соединение, прогресса не
видно). Сборка уходит в поток, страница `/prep/{vid}` показывает прогресс
«этап N из 8» и опрашивает `/prep/{vid}/status`; готовый пакет открывается
по тому же адресу.

Второй режим — «досборка»: если необязательные этапы (4–7) упали, например
по обрыву сети, собираются только они, без повторной оплаты первых трёх.

Состояние задач живёт в памяти процесса (uvicorn запущен одним воркером);
после рестарта контейнера незавершённая сборка забывается, а страница
пакета запустит новую.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime

from agents import interview_prep as ip


@dataclass
class StageInfo:
    key: str
    title: str
    status: str = "pending"     # pending | running | ok | fail | skip
    detail: str = ""
    seconds: float = 0.0


@dataclass
class Job:
    package_id: str
    kind: str                   # full | resume
    started_at: str
    stages: list[StageInfo] = field(default_factory=list)
    done: bool = False
    error: str = ""
    finished_at: str = ""
    t0: float = 0.0
    t1: float = 0.0


_JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get(package_id: str) -> Job | None:
    return _JOBS.get(package_id)


def is_running(package_id: str) -> bool:
    job = _JOBS.get(package_id)
    return job is not None and not job.done


def _progress_for(job: Job):
    started: dict[str, float] = {}

    def cb(key: str, status: str, detail: str = "") -> None:
        for st in job.stages:
            if st.key != key:
                continue
            if status == "start":
                st.status, st.detail = "running", ""
                started[key] = time.time()
            elif status in ("ok", "fail"):
                st.status = status
                st.detail = detail if status == "fail" else ""
                st.seconds = round(time.time() - started.get(key, time.time()), 1)
            break
    return cb


def _run(job: Job, target) -> None:
    try:
        pkg = target(_progress_for(job))
        if pkg is None:
            job.error = "нет сохранённого пакета — нужна полная сборка"
        elif pkg.error:
            job.error = pkg.error
    except Exception as exc:  # noqa: BLE001 — причина уходит на страницу прогресса
        job.error = f"{type(exc).__name__}: {exc}"
    finally:
        for st in job.stages:
            if st.status == "running":
                st.status, st.detail = "fail", st.detail or job.error
            elif st.status == "pending":
                st.status = "skip"
        job.t1 = time.time()
        job.finished_at = _now()
        job.done = True


def _spawn(job: Job, target) -> Job:
    threading.Thread(target=_run, args=(job, target), daemon=True,
                     name=f"prep-{job.package_id}").start()
    return job


def start_full(package_id: str, vacancy: dict) -> Job:
    """Полная сборка в фоне; если сборка уже идёт — вернуть её."""
    with _LOCK:
        cur = _JOBS.get(package_id)
        if cur is not None and not cur.done:
            return cur
        job = Job(package_id=package_id, kind="full", started_at=_now(), t0=time.time(),
                  stages=[StageInfo(k, t) for k, t in ip.STAGES])
        _JOBS[package_id] = job

    def target(progress):
        return ip.build_prep(
            vacancy_text=vacancy.get("description", ""),
            title=vacancy.get("name", ""),
            company=vacancy.get("employer", ""),
            url=vacancy.get("alternate_url", ""),
            package_id=package_id,
            progress=progress,
        )
    return _spawn(job, target)


def start_resume(package_id: str, vacancy_text: str = "") -> Job | None:
    """Досборка недостающих необязательных этапов; None — пакета нет или он с ошибкой."""
    with _LOCK:
        cur = _JOBS.get(package_id)
        if cur is not None and not cur.done:
            return cur
        pkg = ip.load_saved_prep(package_id)
        if pkg is None or pkg.error:
            return None
        present = ip.present_stages(pkg)
        job = Job(package_id=package_id, kind="resume", started_at=_now(), t0=time.time(),
                  stages=[StageInfo(k, t, status="ok" if k in present else "pending",
                                    detail="уже собран" if k in present else "")
                          for k, t in ip.STAGES])
        _JOBS[package_id] = job

    def target(progress):
        return ip.resume_prep(package_id, vacancy_text=vacancy_text, progress=progress)
    return _spawn(job, target)


def wait(package_id: str, timeout: float = 30.0) -> Job | None:
    """Дождаться завершения задачи (для тестов и скриптов)."""
    job = _JOBS.get(package_id)
    t0 = time.time()
    while job is not None and not job.done and time.time() - t0 < timeout:
        time.sleep(0.02)
    return job


def to_dict(job: Job) -> dict:
    end = job.t1 if job.done else time.time()
    return {
        "package_id": job.package_id,
        "kind": job.kind,
        "running": not job.done,
        "done": job.done,
        "error": job.error,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "elapsed": round(end - job.t0) if job.t0 else 0,
        "stages": [asdict(s) for s in job.stages],
    }
