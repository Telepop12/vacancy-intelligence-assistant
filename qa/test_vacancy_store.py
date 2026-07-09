"""
pytest: Vacancy Store + manual vacancy input — offline.
"""
import pytest

from agents import vacancy_store as vs


@pytest.mark.no_llm
def test_hh_id_from_url():
    assert vs.hh_id_from_url("https://hh.ru/vacancy/12345?query=x") == "12345"
    assert vs.hh_id_from_url("https://spb.hh.ru/vacancy/9") == "9"
    assert vs.hh_id_from_url("https://linkedin.com/jobs/1") is None
    assert vs.hh_id_from_url("") is None


@pytest.mark.no_llm
def test_save_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path)
    data = vs.manual_vacancy_dict("Ищем CIO.\nОбязанности…", title="CIO", company="Тест")
    vid = vs.save_vacancy(data)
    assert vid.startswith("m")
    loaded = vs.load_vacancy(vid)
    assert loaded["name"] == "CIO"
    assert loaded["employer"] == "Тест"
    assert "Обязанности" in loaded["description"]


@pytest.mark.no_llm
def test_manual_dict_title_from_first_line():
    d = vs.manual_vacancy_dict("Директор по данным\nОписание роли…")
    assert d["name"] == "Директор по данным"


@pytest.mark.no_llm
def test_resolve_prefers_store_over_network(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path)
    vs.save_vacancy({"name": "Из кеша", "description": "x"}, "777")

    def boom(vid):
        raise AssertionError("network must not be called when cached")
    from agents import hh_api
    monkeypatch.setattr(hh_api, "fetch_vacancy_data", boom)
    assert vs.resolve_vacancy("777")["name"] == "Из кеша"


@pytest.mark.no_llm
def test_resolve_unknown_manual_id_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path)
    from agents import hh_api
    with pytest.raises(hh_api.HHApiError, match="не найдена"):
        vs.resolve_vacancy("m20990101000000")


@pytest.mark.no_llm
def test_vacancy_add_route_manual_text(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import web.app as webapp
    from agents import hh_search

    monkeypatch.setattr(vs, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(hh_search, "STATE_PATH", tmp_path / "state.json")

    client = TestClient(webapp.app)
    resp = client.post("/vacancy/add", data={
        "vac_text": "Директор по ИТ\nСтратегия, бюджет, команда, 1С, ERP.",
        "vac_company": "Ромашка",
    }, follow_redirects=False)
    assert resp.status_code == 303
    vid = resp.headers["location"].rsplit("/", 1)[-1]

    card = client.get(f"/vacancy/{vid}")
    assert card.status_code == 200
    assert "Ромашка" in card.text
    assert "Пакет отклика" in card.text and "Подготовка" in card.text


@pytest.mark.no_llm
def test_vacancy_add_route_empty_is_error(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import web.app as webapp
    client = TestClient(webapp.app)
    resp = client.post("/vacancy/add", data={})
    assert resp.status_code == 200
    assert "Укажите ссылку" in resp.text
