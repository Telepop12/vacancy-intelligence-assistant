"""
pytest: Кокпит 4b — граф-вид Career Match (офлайн; LLM отключён conftest'ом,
career match падает в rule-based fallback — страница всё равно строится).
"""
import pytest

_VACANCY = """
Директор по информационным технологиям (CIO).
Обязанности: ИТ-стратегия, управление ИТ-бюджетом, команда 30+ человек,
ERP, платформа данных, информационная безопасность.
Требования: опыт CIO от 5 лет в производственных компаниях.
"""

_RESUME = """
Гришкин Вячеслав. Директор по информационным технологиям.
Июнь 2023 — Ноябрь 2025. МВПС-Сервис. CIO.
Управлял ИТ-функцией: бюджет 200+ млн, команда 30+, ERP на 1С, DWH/BI.
Июнь 2018 — Апрель 2023. УРАЛХИМ. CDTO.
Цифровая трансформация производства, бюджет 700+ млн, MES, цифровые двойники.
"""


@pytest.mark.no_llm
def test_match_page_renders_graph_view():
    from fastapi.testclient import TestClient
    import web.app as webapp

    client = TestClient(webapp.app)
    page = client.post("/match/analyze", data={
        "vacancy_text": _VACANCY, "resume_text": _RESUME,
    })
    assert page.status_code == 200
    html = page.text
    # граф-вид присутствует и подключён
    assert 'id="graphView"' in html
    assert 'id="cockpitSvg"' in html
    assert "COCKPIT_DATA" in html
    assert "cockpit_graph.js" in html
    # три линзы и переключатель режимов
    assert 'data-lens="match"' in html
    assert 'data-lens="prep"' in html
    assert 'data-lens="letter"' in html
    assert 'id="btnGraph"' in html
    # данные доменов сериализованы (ключи структуры)
    assert '"strengths"' in html or "key: \"strengths\"" in html


@pytest.mark.no_llm
def test_cockpit_static_js_served():
    from fastapi.testclient import TestClient
    import web.app as webapp

    client = TestClient(webapp.app)
    js = client.get("/static/cockpit_graph.js")
    assert js.status_code == 200
    assert "COCKPIT_DATA" in js.text
    assert "setLens" in js.text
