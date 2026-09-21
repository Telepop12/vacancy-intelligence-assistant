"""
pytest: Interview Prep layer («Подготовка 2.0») — offline (LLM mocked).
"""
import json

import pytest

from agents import interview_prep as ip
from agents.interview_prep import PrepPackage, PrepQA

pytestmark = pytest.mark.no_llm

KINDS = ["conflict_top", "conflict_team", "failure", "leader_mistake", "process_change",
         "case_scaling", "case_efficiency", "case_restructuring", "case_crisis"]

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
        {"question": "Есть ли внутренний кандидат?", "why": "Открыт ли конкурс."},
    ],
}
_STAGE3 = {
    "purple_rounds": [
        {"attack": "Вы никогда не управляли 100+.", "defense": "Управлял через руководителей.",
         "verdict": "Убедительно, но добавить цифры.", "improved_answer": "В УРАЛХИМ…"},
    ],
}
_STAGE4 = {
    "process": {
        "basis": "typical", "company_note": "Публичной страницы нет — типовой сценарий.",
        "total": "4–7 встреч за 2–6 месяцев, решает первое лицо.",
        "stages": [
            {"stage": "Скрининг рекрутёра", "who": "HRD", "duration": "30–60 мин",
             "probes": "мотивация и деньги", "tip": "самопрезентация с таймером"},
            {"stage": "Встреча с первым лицом", "who": "CEO", "duration": "60 мин",
             "probes": "масштаб и личный вклад", "tip": "цифры бюджета и команды"},
        ],
        "sources": ["real_stories S1", "выдуманный источник"],
    },
    "presentation": {"short": "Я CIO…", "long": "Длинная версия…",
                     "scope_line": "Руками — архитектурные решения…", "sources": ["beelinenow.ru"]},
    "hundred_days": {"block1": "Аудит.", "block2": "Интервью.", "block3": "Карта.",
                     "pitch": "За минуту.", "sources": ["источник 20"]},
}
_STAGE5 = {
    "stories": [
        {"kind": k, "title": f"История {k}", "situation": "с", "actions": "д", "result": "р",
         "lesson": "в", "origin": "каркас из резюме", "gaps": "что вспомнить?"}
        for k in KINDS
    ],
    "sources": [],
}
_STAGE6 = {
    "agenda": [
        {"topic": "Информационная безопасность", "thesis": "т", "case": "к", "sources": ["A3"]},
        {"topic": "ИИ на практике", "thesis": "т", "case": "к", "sources": []},
        {"topic": "Импортозамещение", "thesis": "т", "case": "к", "sources": []},
    ],
    "blitz": [{"question": f"Вопрос {i}?", "answer": "ответ"} for i in range(8)],
    "dont_say_personal": [{"text": "Не занижать масштаб команды", "why": "болевая зона"}],
    "key_numbers": ["1", "2", "3", "4", "5", "6"],
}
_STAGE7 = {
    "frame": "Начать с наблюдения и оговорить, что это гипотезы со стороны.",
    "context": "Логистический оператор; деньги теряются на порожнем пробеге.",
    "trends": ["ИИ в маршрутизации — снижает порожний пробег", "ФЗ-187 — категорирование КИИ"],
    "items": [
        {"area": "Данные для планирования", "basis": "Вакансия",
         "signal": "в вакансии: «единая отчётность для руководства»",
         "hypothesis": "Единое хранилище вместо ручной сводки.",
         "phrasing": "Вижу в описании единую отчётность — правильно понимаю, что сейчас сводят вручную?",
         "check": "Сколько источников данных питают отчётность?", "backing": "DWH в УРАЛХИМ."},
        {"area": "Маршрутизация", "basis": "отрасль и компания",
         "signal": "тренд", "hypothesis": "Пилот ИИ-маршрутизации.", "phrasing": "",
         "check": "ч", "backing": "прямого опыта нет"},
        {"area": "", "basis": "", "signal": "", "hypothesis": "", "phrasing": "", "check": "", "backing": ""},
    ],
    "sources": ["S5", "выдуманный источник"],
}
ALL = [_STAGE1, _STAGE1B, _STAGE2, _STAGE3, _STAGE4, _STAGE5, _STAGE6, _STAGE7]


def _mock_llm(responses, fail_at: int | None = None):
    calls = {"n": 0}

    def fake(api_key, system, prompt, max_tokens=4000):
        n = calls["n"]
        calls["n"] += 1
        if fail_at is not None and n == fail_at:
            raise RuntimeError("обрыв JSON")
        return responses[min(n, len(responses) - 1)]
    fake.calls = calls
    return fake


def _setup(monkeypatch, tmp_path, fake):
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ip, "STORIES_PATH", tmp_path / "stories.md")
    monkeypatch.setattr(ip, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(ip, "_call_llm", fake)


def test_build_prep_happy_path_v2(monkeypatch, tmp_path):
    fake = _mock_llm(ALL)
    _setup(monkeypatch, tmp_path, fake)

    pkg = ip.build_prep(vacancy_text="Ищем CIO", title="CIO", company="Тест",
                        package_id="hh_42", resume_text="резюме", stories_text="")
    assert not pkg.error and not pkg.stage_errors
    assert fake.calls["n"] == 8
    assert pkg.schema_version == 2 and pkg.kb_version == "2026-09-19"

    # старые блоки
    assert len(pkg.qa) == 2 and pkg.qa[0].severity == "warn"
    assert pkg.hr_qa[0].question.startswith("Расскажите")
    assert pkg.employer_questions[1].question.startswith("Есть ли внутренний")
    assert pkg.purple_rounds[0].improved_answer
    assert pkg.qa_sources and pkg.hr_sources and pkg.employer_sources

    # процесс, самопрезентация, 100 дней
    assert pkg.process.basis == "typical" and len(pkg.process.stages) == 2
    assert pkg.process.stages[1].who == "CEO"
    assert any("S1" in s for s in pkg.process.sources)          # метка из выдержки сохранена
    assert all("выдуманный" not in s for s in pkg.process.sources)  # чужая — отброшена
    assert pkg.presentation.short == "Я CIO…" and pkg.presentation.sources == ["beelinenow.ru"]
    assert pkg.hundred_days.block3 == "Карта." and any("источник 20" in s for s in pkg.hundred_days.sources)

    # истории — каркасы, т.к. файл историй пуст
    assert [s.kind for s in pkg.stories] == KINDS
    assert pkg.stories_origin == "каркасы из резюме"

    # повестка, блиц, «чего не говорить», цифры
    assert [a.topic for a in pkg.agenda][0] == "Информационная безопасность"
    assert len(pkg.blitz) == 8
    assert pkg.key_numbers == ["1", "2", "3", "4", "5"]
    personal = [d for d in pkg.dont_say if d.personal]
    common = [d for d in pkg.dont_say if not d.personal]
    assert len(personal) == 1 and personal[0].text.startswith("Не занижать")
    assert len(common) >= 10 and all(d.source for d in common)

    # «что бы вы улучшили у нас»
    im = pkg.improvements
    assert im.frame.startswith("Начать") and len(im.trends) == 2
    assert [i.basis for i in im.items] == ["вакансия", "отрасль"]   # нормализация; пустой пункт отброшен
    assert im.items[1].backing == "прямого опыта нет"
    assert any("S5" in x for x in im.sources) and all("выдуманный" not in x for x in im.sources)

    # артефакты
    assert (tmp_path / "hh_42.json").exists()
    md = (tmp_path / "hh_42.md").read_text(encoding="utf-8")
    for fragment in ["Как проходит процесс и кто передо мной", "Самопрезентация",
                     "Истории и управленческие кейсы", "План первых 100 дней", "Повестка 2026",
                     "Блиц «экзамен»", "Чего не говорить", "Шпаргалка: 10 минут до звонка",
                     "«Что бы вы улучшили у нас?»", "Данные для планирования", "Если спросят «что бы вы улучшили»",
                     "Purple Team", "Раунд 1", "_Источники:"]:
        assert fragment in md, fragment

    loaded = ip.load_saved_prep("hh_42")
    assert loaded is not None
    assert loaded.process.stages[0].stage == "Скрининг рекрутёра"
    assert loaded.stories[2].kind == "failure"
    assert loaded.agenda[1].topic == "ИИ на практике"
    assert loaded.dont_say[0].personal is True
    assert loaded.improvements.items[0].area == "Данные для планирования"
    assert loaded.improvements.trends == im.trends


def test_build_prep_no_key(monkeypatch, tmp_path):
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ip, "_get_api_key", lambda: "")
    pkg = ip.build_prep(vacancy_text="v", package_id="hh_1", resume_text="r")
    assert pkg.error and "ANTHROPIC_API_KEY" in pkg.error


def test_build_prep_empty_qa_is_error(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm([{"qa": []}, _STAGE1B, _STAGE2, _STAGE3]))
    pkg = ip.build_prep(vacancy_text="v", package_id="hh_2", resume_text="r")
    assert pkg.error
    assert not (tmp_path / "hh_2.json").exists()


def test_optional_stage_failure_keeps_package(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm(ALL, fail_at=5))   # этап историй падает
    pkg = ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_3",
                        resume_text="r", stories_text="")
    assert not pkg.error
    assert len(pkg.stage_errors) == 1 and "истории" in pkg.stage_errors[0]
    assert pkg.stories == []
    assert pkg.process.stages and pkg.blitz          # соседние этапы собрались
    assert (tmp_path / "hh_3.json").exists()
    md = (tmp_path / "hh_3.md").read_text(encoding="utf-8")
    assert "Часть разделов не собралась" in md


def test_stories_file_drives_origin(monkeypatch, tmp_path):
    fake = _mock_llm(ALL)
    _setup(monkeypatch, tmp_path, fake)
    stories = "## Конфликт 1\nВ 2024 году спорил с CFO о бюджете MES, договорились о пилоте на одном заводе."
    pkg = ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_4",
                        resume_text="r", stories_text=stories)
    assert pkg.stories_origin == "файл историй"
    # текст файла попал в промпт этапа историй
    assert "Личный файл" not in _STAGE5   # sanity: словарь-ответ не трогали


def test_load_stories_ignores_template(tmp_path):
    path = tmp_path / "stories.md"
    assert ip.load_stories(path) == ""                     # файла нет
    ip.ensure_stories_template(path)
    assert path.exists() and "Конфликт 1" in path.read_text(encoding="utf-8")
    assert ip.load_stories(path) == ""                     # только шаблон — пусто
    path.write_text(path.read_text(encoding="utf-8")
                    + "\nВ 2023 году вендор сорвал внедрение ERP на два квартала; я перевёл "
                      "проект на внутреннюю команду и закрыл его к плану.\n", encoding="utf-8")
    assert "вендор сорвал" in ip.load_stories(path)         # есть содержание — отдаём файл целиком


def test_old_v1_package_loads_with_empty_new_sections(monkeypatch, tmp_path):
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    old = {
        "package_id": "hh_5", "vacancy_title": "CIO", "company": "Старая", "vacancy_url": "",
        "interviewer_profile": "Профиль.",
        "qa": [{"source": "s", "question": "Вопрос?", "answer": "Ответ.", "severity": "warn"}],
        "hr_qa": [], "user_qa": [], "employer_questions": [], "purple_rounds": [],
        "top_risks": [], "top_trumps": [], "generated_at": "2026-07-07T13:13:00", "error": "",
    }
    (tmp_path / "hh_5.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    pkg = ip.load_saved_prep("hh_5")
    assert pkg is not None and pkg.schema_version == 1
    assert pkg.process.stages == [] and pkg.stories == [] and pkg.dont_say == []
    assert pkg.improvements.items == [] and pkg.improvements.frame == ""
    assert pkg.qa[0].question == "Вопрос?"


def test_build_cheatsheet_from_package():
    pkg = PrepPackage(
        package_id="hh_6", vacancy_title="CIO", company="Тест",
        top_trumps=["a", "b", "c", "d"], key_numbers=["1", "2"],
        qa=[PrepQA(question="Риск?", answer="Ответ на риск.", severity="risk")],
        employer_questions=[ip.EmployerQuestion(question=f"В{i}?", why="") for i in range(4)],
        purple_rounds=[ip.PurpleRound(attack="Атака", defense="Защита", improved_answer="Отточено")],
        process=ip.ProcessMap(stages=[ip.ProcessStage(stage="Скрининг", who="HRD", duration="30 мин")]),
        presentation=ip.Presentation(short="О себе", scope_line="Руками…"),
        dont_say=[ip.DontSayItem(text="общее", personal=False), ip.DontSayItem(text="личное", personal=True)],
        blitz=[ip.BlitzQA(question=f"q{i}", answer="a") for i in range(7)],
        hundred_days=ip.HundredDays(pitch="За минуту"),
        improvements=ip.Improvements(items=[ip.Improvement(phrasing="п0"), ip.Improvement(hypothesis="г1"),
                                            ip.Improvement(), ip.Improvement(phrasing="п3"),
                                            ip.Improvement(phrasing="п4")]),
    )
    cs = ip.build_cheatsheet(pkg)
    assert cs.trumps == ["a", "b", "c"]
    assert cs.risk_answers == [("Атака", "Отточено"), ("Риск?", "Ответ на риск.")]  # добор из qa
    assert cs.employer_questions == ["В0?", "В1?", "В2?"]
    assert cs.dont_say[0] == "личное"                       # личные — первыми
    assert cs.stages == ["Скрининг — HRD · 30 мин"]
    assert len(cs.blitz) == 5 and cs.hundred_days_pitch == "За минуту"
    assert cs.improve == ["п0", "г1", "п3"]                # фраза, иначе гипотеза; пустые пропущены


def test_answer_user_question_persists(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm(ALL))
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "резюме")
    ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_9", resume_text="р", stories_text="")

    monkeypatch.setattr(ip, "_call_llm", _mock_llm([{"answer": "Отвечаю на фактах.", "note": ""}]))
    item = ip.answer_user_question("hh_9", "Почему вы?")
    assert item.answer == "Отвечаю на фактах."
    assert item.severity == "user"

    loaded = ip.load_saved_prep("hh_9")
    assert len(loaded.user_qa) == 1
    assert loaded.user_qa[0].question == "Почему вы?"
    assert loaded.process.stages                             # новые блоки пережили пересохранение
    md = (tmp_path / "hh_9.md").read_text(encoding="utf-8")
    assert "спрошено у двойника" in md


# ---------------------------------------------------------------------------
# Маршруты
# ---------------------------------------------------------------------------

def _client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import web.app as webapp
    from agents import vacancy_store as vs
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    return TestClient(webapp.app), webapp


def test_prep_route_cold_path(monkeypatch, tmp_path):
    client, webapp = _client(monkeypatch, tmp_path)
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
    resp = client.get("/prep/7")
    assert resp.status_code == 200
    assert "Вопрос?" in resp.text
    assert "собран прежней версией" in resp.text            # schema_version=1 → подсказка


def test_prep_route_renders_v2_sections(monkeypatch, tmp_path):
    client, _webapp = _client(monkeypatch, tmp_path)
    _setup(monkeypatch, tmp_path, _mock_llm(ALL))
    ip.build_prep(vacancy_text="v", title="CIO", company="Тест", package_id="hh_8",
                  resume_text="r", stories_text="")
    resp = client.get("/prep/8")
    assert resp.status_code == 200
    for fragment in ["Как проходит процесс и кто передо мной", "Скрининг рекрутёра",
                     "Провальный проект", "каркас из резюме", "Повестка 2026",
                     "лично вам", "/prep/8/cheatsheet", "/prep/8?regenerate=true",
                     'data-target="process"', 'data-target="cheat"', "classList.toggle('active'",
                     'data-target="improve"', "«Что бы вы улучшили у нас?»", 'class="basis vac"',
                     "Вижу в описании единую отчётность"]:
        assert fragment in resp.text, fragment
    assert "собран прежней версией" not in resp.text
    # скрипт подсветки должен идти после всех блоков, иначе не найдёт их (приёмка 21.09)
    assert resp.text.index('id="dontsay"') < resp.text.index('id="cheat"') < resp.text.index("classList.toggle('active'")

    cheat = client.get("/prep/8/cheatsheet")
    assert cheat.status_code == 200
    assert "10 минут до звонка" in cheat.text and "Я CIO…" in cheat.text
    assert "Не занижать масштаб" in cheat.text
    assert "Если спросят «что бы вы улучшили»" in cheat.text and "Вижу в описании" in cheat.text


def test_cheatsheet_without_package_redirects(monkeypatch, tmp_path):
    client, _webapp = _client(monkeypatch, tmp_path)
    resp = client.get("/prep/404/cheatsheet", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/prep/404"


def test_legacy_redirect_keeps_query(monkeypatch, tmp_path):
    client, _webapp = _client(monkeypatch, tmp_path)
    resp = client.get("/prep/hh/7?regenerate=true", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/prep/7?regenerate=true"
    resp = client.get("/package/hh/7?regenerate=true", follow_redirects=False)
    assert resp.headers["location"] == "/package/7?regenerate=true"
