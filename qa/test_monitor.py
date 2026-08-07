"""
pytest: Monitor cycle — offline (search, packages, telegram все замоканы).
"""
from datetime import datetime

import pytest

from agents import monitor
from agents.hh_search import SearchRunResult, TriageItem


def _item(vid, score, title="CIO", triaged_at=None):
    return TriageItem(
        hh_id=vid, title=title, company="Тест", score=score,
        recommendation="ОТКЛИКАТЬСЯ" if score >= 65 else "УТОЧНИТЬ",
        triaged_at=triaged_at or datetime.now().isoformat(timespec="seconds"),
    )


class _Pkg:
    error = ""


@pytest.fixture
def env(monkeypatch, tmp_path):
    from agents import hh_search, vacancy_store, application_package as ap
    monkeypatch.setattr(monitor, "DIGEST_PATH", tmp_path / "digest.json")
    monkeypatch.setattr(monitor, "TG_STATE_PATH", tmp_path / "tg.json")
    monkeypatch.setattr(monitor, "load_monitor_config", lambda: {
        "enabled": True, "interval_hours": 6,
        "score_threshold": 60, "max_packages_per_cycle": 2,
    })
    monkeypatch.setattr(vacancy_store, "resolve_vacancy",
                        lambda vid: {"name": "CIO", "description": "текст"})
    monkeypatch.setattr(ap, "load_saved_package", lambda pid: None)
    built = []
    def fake_build(**kw):
        built.append(kw["package_id"])
        return _Pkg()
    monkeypatch.setattr(ap, "build_package", fake_build)
    sent = []
    monkeypatch.setattr(monitor, "send_telegram", lambda text: sent.append(text) or True)
    return {"hh_search": hh_search, "built": built, "sent": sent, "monkeypatch": monkeypatch}


@pytest.mark.no_llm
def test_cycle_threshold_and_package_cap(env):
    items = [_item("1", 80), _item("2", 70), _item("3", 65), _item("4", 40)]
    env["monkeypatch"].setattr(
        env["hh_search"], "run_search",
        lambda profile: SearchRunResult(items=items, new_count=4, found_total=4, skipped_backlog=0),
    )
    r = monitor.run_cycle(profile=None)
    assert r.new_strong == 3            # 40 отсечён порогом
    assert r.packages_built == 2        # cap = 2
    assert r.notified is True
    assert len(env["sent"]) == 1 and "80" in env["sent"][0]

    digest = monitor.load_digest()
    assert len(digest) == 3
    assert sum(1 for e in digest if e["package_ready"]) == 2


@pytest.mark.no_llm
def test_cycle_lookback_covers_manual_search(env):
    """Вакансия, оттриажированная вчера ручным поиском, попадает в цикл;
    старше lookback_hours — нет."""
    from datetime import timedelta
    yesterday = (datetime.now() - timedelta(hours=20)).isoformat(timespec="seconds")
    week_ago = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
    items = [
        _item("10", 82, triaged_at=yesterday),
        _item("11", 75, triaged_at=week_ago),
    ]
    env["monkeypatch"].setattr(
        env["hh_search"], "run_search",
        lambda profile: SearchRunResult(items=items, new_count=1, found_total=2, skipped_backlog=0),
    )
    r = monitor.run_cycle(profile=None)
    assert r.new_strong == 1
    digest = monitor.load_digest()
    assert [e["vid"] for e in digest] == ["10"]


@pytest.mark.no_llm
def test_cycle_known_vacancies_not_repeated(env):
    items = [_item("1", 80)]
    env["monkeypatch"].setattr(
        env["hh_search"], "run_search",
        lambda profile: SearchRunResult(items=items, new_count=1, found_total=1, skipped_backlog=0),
    )
    r1 = monitor.run_cycle(profile=None)
    assert r1.new_strong == 1
    r2 = monitor.run_cycle(profile=None)  # та же вакансия — уже в дайджесте
    assert r2.new_strong == 0
    assert len(monitor.load_digest()) == 1


@pytest.mark.no_llm
def test_cycle_search_failure_is_graceful(env):
    def boom(profile):
        raise RuntimeError("hh недоступен")
    env["monkeypatch"].setattr(env["hh_search"], "run_search", boom)
    r = monitor.run_cycle(profile=None)
    assert r.errors and "hh недоступен" in r.errors[0]
    assert r.new_strong == 0


@pytest.mark.no_llm
def test_telegram_silent_when_unconfigured(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "TG_STATE_PATH", tmp_path / "tg.json")
    monkeypatch.setattr(monitor, "_tg_token", lambda: "")
    assert monitor.send_telegram("test") is False
    assert monitor.telegram_status() == "off"


@pytest.mark.no_llm
def test_digest_page(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import web.app as webapp
    monkeypatch.setattr(monitor, "DIGEST_PATH", tmp_path / "digest.json")
    monitor._save_digest([{
        "vid": "9", "title": "CIO мечты", "company": "К", "score": 88,
        "recommendation": "ОТКЛИКАТЬСЯ", "found_at": "2026-08-04T12:00:00",
        "package_ready": True, "notified": True,
    }])
    client = TestClient(webapp.app)
    page = client.get("/digest")
    assert page.status_code == 200
    assert "CIO мечты" in page.text and "Пакет готов" in page.text
