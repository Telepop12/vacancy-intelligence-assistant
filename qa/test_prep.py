"""
pytest: Interview Prep layer — offline (LLM mocked).
"""
import pytest

from agents import interview_prep as ip
from agents.interview_prep import PrepPackage, PrepQA


_STAGE1 = {
    "interviewer_profile": "Дотошный CEO логистического оператора.",
    "qa": [
        {"source": "доступность 99,9%", "question": "Как считали 99,9%?",
         "answer": "SLA по каталогу сервисов, мониторинг; плановые окна исключались.",
         "severity": "warn"},
        {"source": "команда 30+", "question": "Почему справитесь со 100+?",
         "answer": "Через матричное управление в УРАЛХИМ.", "severity": "risk"},
    ],
    "top_risks": ["масштаб команды"],
    "top_trumps": ["AI-портфель"],
}
_STAGE1B = {
    "hr_qa": [
        {"source": "самопрезентация", "question": "Расскажите о себе.",
         "answer": "CIO с опытом трансформации…", "severity": "hr"},
    ],
}
_STAGE2 = {
    "employer_questions": [
        {"question": "Каков мандат роли?", "why": "Показывает мышление уровня C-Level."},
    ],
}
_STAGE3 = {
    "purple_rounds": [
        {"attack": "Вы никогда не управляли 100+.", "defense": "Управлял через руководителей.",
         "verdict": "Убедительно, но добавить цифры.", "improved_answer": "В УРАЛХИМ…"},
    ],
}


def _mock_llm(responses):
    calls = {"n": 0}
    def fake(api_key, system, prompt, max_tokens=4000):
        r = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        return r
    return fake


@pytest.mark.no_llm
def test_build_prep_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ip, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(ip, "_call_llm", _mock_llm([_STAGE1, _STAGE1B, _STAGE2, _STAGE3]))

    pkg = ip.build_prep(vacancy_text="Ищем CIO", title="CIO", company="Тест",
                        package_id="hh_42", resume_text="резюме")
    assert not pkg.error
    assert len(pkg.qa) == 2 and pkg.qa[0].severity == "warn"
    assert pkg.hr_qa[0].question.startswith("Расскажите")
    assert pkg.employer_questions[0].question.startswith("Каков")
    assert pkg.purple_rounds[0].improved_answer
    assert (tmp_path / "hh_42.json").exists()
    assert (tmp_path / "hh_42.md").exists()

    md = (tmp_path / "hh_42.md").read_text(encoding="utf-8")
    for fragment in ["Кто вас будет спрашивать", "Козыри", "поведенческие вопросы",
                     "Purple Team", "Раунд 1"]:
        assert fragment in md, fragment

    loaded = ip.load_saved_prep("hh_42")
    assert loaded is not None
    assert loaded.qa[1].question == pkg.qa[1].question
    assert loaded.hr_qa[0].source == "самопрезентация"


@pytest.mark.no_llm
def test_build_prep_no_key(monkeypatch, tmp_path):
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ip, "_get_api_key", lambda: "")
    pkg = ip.build_prep(vacancy_text="v", package_id="hh_1", resume_text="r")
    assert pkg.error and "ANTHROPIC_API_KEY" in pkg.error


@pytest.mark.no_llm
def test_build_prep_empty_qa_is_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ip, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(ip, "_call_llm", _mock_llm([{"qa": []}, _STAGE1B, _STAGE2, _STAGE3]))
    pkg = ip.build_prep(vacancy_text="v", package_id="hh_2", resume_text="r")
    assert pkg.error
    assert not (tmp_path / "hh_2.json").exists()


@pytest.mark.no_llm
def test_prep_route_cold_path(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import web.app as webapp

    from agents import vacancy_store as vs
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        webapp.hh_api, "fetch_vacancy_data",
        lambda vid: {"name": "CIO", "employer": "Тест", "description": "текст",
                     "alternate_url": "https://hh.ru/vacancy/7"},
    )
    monkeypatch.setattr(
        webapp, "build_prep",
        lambda **kw: PrepPackage(package_id="hh_7", vacancy_title="CIO",
                                 interviewer_profile="Профиль.",
                                 qa=[PrepQA(question="Вопрос?", answer="Ответ.", severity="warn")]),
    )
    client = TestClient(webapp.app)
    resp = client.get("/prep/hh/7")
    assert resp.status_code == 200
    assert "Вопрос?" in resp.text
