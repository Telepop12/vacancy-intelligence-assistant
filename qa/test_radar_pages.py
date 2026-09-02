"""
pytest: страницы радара и таргет-листа рендерятся (офлайн, только GET —
состояние на диске не меняется).
"""
import pytest

from agents import hh_api, hh_search, mail_radar, vacancy_store
from core.models import CandidateProfile, ScoringGroup


def _profile() -> CandidateProfile:
    return CandidateProfile(
        name="Тест", target_roles=["CIO"],
        scoring_groups={"core": ScoringGroup(weight=100, keywords=["ИТ-стратегия"])},
        red_flags={}, seniority_keywords=[],
    )


def _intake(vid: str, name: str) -> dict:
    return {"name": name, "employer": "Работодатель", "area": "Москва", "salary": None,
            "alternate_url": f"https://hh.ru/vacancy/{vid}", "published_at": "2026-09-01",
            "hh_id": vid, "description": "Обязанности: ИТ-стратегия. Требования: опыт. Условия: офис."}


@pytest.fixture()
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(mail_radar, "STATE_PATH", tmp_path / "radar.json")
    monkeypatch.setattr(hh_search, "STATE_PATH", tmp_path / "search.json")
    monkeypatch.setattr(vacancy_store, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(vacancy_store, "FAV_PATH", tmp_path / "fav.json")
    monkeypatch.setattr(hh_api, "_COOLDOWN_PATH", tmp_path / "cooldown.json")


@pytest.mark.no_llm
def test_radar_rows_merge_sources(_isolated):
    p = _profile()
    hh_search.register_vacancy(p, _intake("1", "Директор по ИТ"), "1", source="mail:hh", resume_variant="CIO")
    hh_search.register_vacancy(p, _intake("2", "Обычный автопоиск"), "2")            # не в ленте
    hh_search.register_vacancy(p, _intake("c3", "CDTO"), "c3", source="career:СИБУР")
    state = mail_radar.load_state()
    state["leads"]["linkedin:9"] = {
        "source": "linkedin", "ext_id": "9", "title": "Head of IT", "company": "Etihad",
        "location": "Абу-Даби", "salary": "", "url": "https://www.linkedin.com/jobs/view/9/",
        "email_date": "2026-09-02", "status": "new", "times_seen": 2, "checked_at": "2026-09-02T18:00:00",
    }
    mail_radar.save_state(state)

    rows = mail_radar.radar_rows()
    kinds = {r["kind"] for r in rows}
    assert kinds == {"hh", "career", "linkedin"}
    assert not any(r["vid"] == "2" for r in rows)
    li = next(r for r in rows if r["kind"] == "linkedin")
    assert li["score"] is None and li["key"] == "linkedin:9" and li["times_seen"] == 2
    hh_row = next(r for r in rows if r["kind"] == "hh")
    assert hh_row["score"] > 0 and hh_row["resume_variant"] == "CIO" and hh_row["source_label"] == "hh · рассылка"
    career = next(r for r in rows if r["kind"] == "career")
    assert career["source_label"] == "СИБУР" and career["vid"] == "c3"
    # свежие первыми: LinkedIn от 02.09 выше hh от 01.09
    assert rows[0]["kind"] == "linkedin"


@pytest.mark.no_llm
def test_dismiss_hides_from_radar_and_survives(monkeypatch, _isolated, tmp_path):
    monkeypatch.setattr(vacancy_store, "DISMISSED_PATH", tmp_path / "dismissed.json")
    p = _profile()
    hh_search.register_vacancy(p, _intake("1", "Директор по ИТ"), "1", source="mail:hh")
    hh_search.register_vacancy(p, _intake("c3", "CDTO"), "c3", source="career:СИБУР")
    vacancy_store.add_favorite("1")

    vacancy_store.dismiss("1")
    assert vacancy_store.is_dismissed("1")
    assert not vacancy_store.is_favorite("1")                 # пропущенная не избранная
    assert [r["vid"] for r in mail_radar.radar_rows()] == ["c3"]
    assert [r["vid"] for r in mail_radar.radar_rows(include_dismissed=True)] == ["1", "c3"] or \
           {r["vid"] for r in mail_radar.radar_rows(include_dismissed=True)} == {"1", "c3"}
    assert [d["vid"] for d in mail_radar.dismissed_rows()] == ["1"]
    # Запись осталась в состоянии поиска — автопоиск не загрузит её заново
    assert hh_search.get_state_item("1") is not None

    vacancy_store.undismiss("1")
    assert {r["vid"] for r in mail_radar.radar_rows()} == {"1", "c3"}


@pytest.mark.no_llm
def test_dismiss_endpoints(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import web.app as webapp
    monkeypatch.setattr(vacancy_store, "DISMISSED_PATH", tmp_path / "dismissed.json")
    monkeypatch.setattr(vacancy_store, "FAV_PATH", tmp_path / "fav.json")

    client = TestClient(webapp.app)
    assert client.post("/vacancy/777/dismiss").json() == {"dismissed": True}
    assert vacancy_store.list_dismissed() == ["777"]
    assert client.post("/vacancy/777/undismiss").json() == {"dismissed": False}
    assert vacancy_store.list_dismissed() == []


@pytest.mark.no_llm
def test_radar_and_targets_pages_render():
    from fastapi.testclient import TestClient
    import web.app as webapp

    client = TestClient(webapp.app)
    radar = client.get("/radar")
    assert radar.status_code == 200
    assert "Радар источников" in radar.text
    assert 'data-kind="hh"' in radar.text          # кнопка фильтра
    assert 'id="sortBy"' in radar.text

    targets = client.get("/targets")
    assert targets.status_code == 200
    assert "Таргет-лист компаний" in targets.text
    assert "Обойти все компании" in targets.text
