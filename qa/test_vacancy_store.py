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
def test_favorites_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(vs, "FAV_PATH", tmp_path / "fav.json")
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path / "store")
    assert vs.list_favorites() == []
    vs.add_favorite("111")
    vs.add_favorite("m2026")
    vs.add_favorite("111")  # idempotent
    assert vs.list_favorites() == ["111", "m2026"]
    assert vs.is_favorite("111")
    vs.remove_favorite("111")
    assert vs.list_favorites() == ["m2026"]

    vs.save_vacancy({"name": "X", "description": "y"}, "m2026")
    vs.delete_vacancy("m2026")
    assert vs.list_favorites() == []
    assert vs.load_vacancy("m2026") is None


@pytest.mark.no_llm
def test_favorites_page_and_toggle(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import web.app as webapp
    from agents import hh_search

    monkeypatch.setattr(vs, "FAV_PATH", tmp_path / "fav.json")
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(hh_search, "STATE_PATH", tmp_path / "state.json")

    client = TestClient(webapp.app)
    # add manual vacancy → toggle favorite → visible on /favorites
    marker = "Директор по данным Квантовой Ромашки"
    resp = client.post("/vacancy/add", data={"vac_text": f"{marker}\nСтратегия, ERP."},
                       follow_redirects=False)
    vid = resp.headers["location"].rsplit("/", 1)[-1]
    assert client.post(f"/favorites/toggle/{vid}").json() == {"favorite": True}
    page = client.get("/favorites")
    assert page.status_code == 200 and marker in page.text
    # delete removes everywhere
    client.post(f"/vacancy/{vid}/delete", follow_redirects=False)
    assert vs.list_favorites() == []
    assert marker not in client.get("/favorites").text


@pytest.mark.no_llm
def test_rescan_keeps_state_on_fetch_failure(monkeypatch, tmp_path):
    """Regression: rescan + rate limit must NOT wipe the base (lost 49 items live)."""
    from agents import hh_search, hh_api
    from web.app import _profile

    monkeypatch.setattr(hh_search, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(
        hh_api, "search_vacancy_ids",
        lambda text, area=None, max_pages=1, search_field="name", extra_params=None: ["301"],
    )
    ok = lambda ids: ({vid: {"name": "CIO", "description": "текст", "hh_id": vid} for vid in ids}, {}, False)
    fail = lambda ids: ({}, {vid: "HTTP 423" for vid in ids}, True)

    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", ok)
    r1 = hh_search.run_search(_profile, queries=["CIO"])
    assert r1.new_count == 1

    monkeypatch.setattr(hh_api, "fetch_vacancies_batch", fail)
    r2 = hh_search.run_search(_profile, queries=["CIO"], rescan=True)
    assert len([i for i in r2.items if not i.error]) == 1  # база уцелела


@pytest.mark.no_llm
def test_vacancy_add_route_empty_is_error(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import web.app as webapp
    client = TestClient(webapp.app)
    resp = client.post("/vacancy/add", data={})
    assert resp.status_code == 200
    assert "Укажите ссылку" in resp.text
