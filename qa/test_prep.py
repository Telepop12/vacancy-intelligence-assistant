"""
pytest: Interview Prep layer — offline (модель и веб-поиск подменены).

Подменённая модель отвечает по виду этапа (по системному промпту), а не по
порядку вызовов: необязательные этапы идут параллельно, порядок не задан.
"""
import json
import threading

import pytest

from agents import company_research as cr
from agents import interview_prep as ip
from agents import practice_research as pr
from agents import prep_jobs
from agents.interview_prep import PrepPackage, PrepQA
from core.llm import ResearchResult

pytestmark = pytest.mark.no_llm

KINDS = ["conflict_top", "conflict_team", "failure", "leader_mistake", "process_change",
         "case_scaling", "case_efficiency", "case_restructuring", "case_crisis"]
OPTIONAL = {"presentation", "team", "stories", "agenda", "improve"}

_COMPANY_DATA = {
    "legal_name": "ООО «Тест-Клиника»",
    "summary": "Сеть клиник в Москве и области, 40 площадок.",
    "sections": [
        {"key": "scale", "text": "40 клиник, 3000 сотрудников (2025).",
         "sources": ["https://www.rusprofile.ru/id/1"]},
        {"key": "owners", "text": "Основатель владеет 100%.", "sources": ["https://fake.example/owner"]},
        {"topic": "Финансовые показатели", "text": "в открытых источниках не найдено", "sources": []},
        {"key": "it", "text": "Внедрена МИС, проекты с интегратором (2024).",
         "sources": ["https://tadviser.ru/a/1/"]},
        {"key": "nonsense", "text": "мусор", "sources": []},
        "не словарь",
    ],
    "talking_points": ["40 клиник — поддержка распределённой сети", "МИС внедрена — вопрос интеграций"],
    "gaps": "Неизвестна численность ИТ.",
}
_COMPANY = ResearchResult(
    data=_COMPANY_DATA,
    sources=[{"url": "https://www.rusprofile.ru/id/1", "title": "Rusprofile"},
             {"url": "https://tadviser.ru/a/1", "title": "TAdviser: МИС"}],
    searches=7,
)

_STAGE1 = {
    "interviewer_profile": "Дотошный CEO логистического оператора.",
    "qa": [
        {"source": "доступность 99,9%", "question": "Как считали 99,9%?", "lead": "опыт",
         "understanding": "", "answer": "SLA по каталогу сервисов, мониторинг; плановые окна исключались.",
         "severity": "warn"},
        {"source": "пробел: потоковая аналитика", "question": "Как бы вы построили стрим-аналитику?",
         "lead": "Понимание (пробел в резюме)",
         "understanding": "Kafka как шина, потоковая обработка во Flink, витрины в ClickHouse.",
         "answer": "Цифровой советчик в УРАЛХИМ работал на потоке данных установок.", "severity": "risk"},
        {"source": "команда 30+", "question": "Почему справитесь со 100+?", "lead": "понимание",
         "understanding": "", "answer": "Через матричное управление в УРАЛХИМ.", "severity": "risk"},
        {"source": "", "question": "  ", "answer": "пустой вопрос отбрасывается"},
    ],
    "top_risks": ["масштаб команды"],
    "top_trumps": ["AI-портфель"],
}
_STAGE1B = {
    "hr_qa": [
        {"source": "мотивация", "question": "Почему вы в поиске?", "lead": "опыт",
         "understanding": "Ищу масштаб.", "answer": "Завершил трансформацию в МВПС.", "severity": "что угодно"},
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
_PRES = {
    "presentation": {"who": "Я CIO…", "experience": "Путь через УРАЛХИМ и МВПС…",
                     "seeking": "Ищу роль, где ИТ — часть стратегии…", "sources": ["beelinenow.ru"]},
    "hundred_days": {"block1": "Аудит.", "block2": "Интервью.", "block3": "Карта.",
                     "pitch": "За минуту.", "sources": ["источник 20"]},
}
_TEAM = {
    "structure": {
        "estimate": "Оценка: ИТ-функция 25–35 человек, часть поддержки на аутсорсе.",
        "units": [{"name": "Поддержка клиник", "size": "10–14", "scope": "первая и вторая линия",
                   "note": "штат + аутсорс выездных инженеров"},
                  {"name": "", "size": "1", "scope": "без названия — отбрасывается"}],
        "clarify": ["Сколько людей в ИТ сейчас?", " "],
        "sources": ["S4", "выдуманный источник"],
    },
    "structure_qa": [
        {"source": "оптимизировать", "question": "Как сократите ИТ на 20%?", "lead": "понимание",
         "understanding": "Сначала каталог услуг и загрузка, потом решения.", "answer": "Пересобирал ИТ в МВПС."},
    ],
    "people_qa": [
        {"source": "увольнение", "question": "Ваш сотрудник саботирует изменения. Ваши действия?",
         "lead": "опыт", "understanding": "Разговор, план, срок, решение.",
         "answer": "Кандидат добавит свой пример."},
    ],
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
         "check": "ч", "backing": "прямого опыта нет", "practice_ids": ["P1"]},
        {"area": "", "basis": "", "signal": "", "hypothesis": "", "phrasing": "", "check": "", "backing": ""},
    ],
    "sources": ["S5", "выдуманный источник"],
}


def _table():
    return {
        ip._QA_SYSTEM: ("qa", _STAGE1), ip._HR_SYSTEM: ("hr", _STAGE1B),
        ip._EMP_SYSTEM: ("employer", _STAGE2), ip._PURPLE_SYSTEM: ("purple", _STAGE3),
        ip._PRES_SYSTEM: ("presentation", _PRES), ip._TEAM_SYSTEM: ("team", _TEAM),
        ip._STORIES_SYSTEM: ("stories", _STAGE5), ip._AGENDA_SYSTEM: ("agenda", _STAGE6),
        ip._IMPR_SYSTEM: ("improve", _STAGE7),
    }


def _mock_llm(fail=(), override=None, hook=None):
    """Модель по виду этапа; fail — этапы, которые падают; hook(stage) — перед ответом."""
    table = _table()
    calls = {"n": 0, "stages": [], "prompts": {}, "materials": {}}
    lock = threading.Lock()

    def fake(api_key, system, prompt, max_tokens=4000, **kw):
        stage, resp = table[system]
        with lock:
            calls["n"] += 1
            calls["stages"].append(stage)
            calls["prompts"][stage] = prompt
            calls["materials"][stage] = kw.get("materials", "")
        if hook:
            hook(stage)
        if stage in fail:
            raise RuntimeError("обрыв JSON")
        return (override or {}).get(stage, resp)
    fake.calls = calls
    return fake


def _mock_research(result=None, fail=False):
    calls = {"n": 0, "prompts": [], "kw": []}

    def fake(api_key, system, prompt, **kw):
        calls["n"] += 1
        calls["prompts"].append(prompt)
        calls["kw"].append(kw)
        if fail:
            raise RuntimeError("поиск недоступен")
        return result or _COMPANY
    fake.calls = calls
    return fake


def _setup(monkeypatch, tmp_path, fake, research=None):
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ip, "STORIES_PATH", tmp_path / "stories.md")
    monkeypatch.setattr(ip, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(ip, "_call_llm", fake)
    monkeypatch.setattr(pr, "get_practices", lambda *args, **kwargs: pr.PracticeBrief(practices=[
        pr.Practice(id="P1", title="Маршрутизация", process="Планирование рейсов",
                    application="Подсказка диспетчеру", metric="Порожний пробег",
                    vacancy_quote="Задача планирования", company_quote="Распределённая сеть",
                    fit="Общая задача сети", limits="Нужны данные маршрутов",
                    sources=["https://example.org/case"]),
    ]))
    research = research or _mock_research()
    monkeypatch.setattr(cr, "_call_research", research)
    return research


def test_build_prep_happy_path_v3(monkeypatch, tmp_path):
    fake = _mock_llm()
    research = _setup(monkeypatch, tmp_path, fake)

    pkg = ip.build_prep(vacancy_text="Ищем CIO", title="CIO", company="Тест", package_id="hh_42",
                        resume_text="резюме", stories_text="")
    assert not pkg.error and not pkg.stage_errors
    assert fake.calls["n"] == 9 and research.calls["n"] == 1
    assert sorted(fake.calls["stages"]) == sorted(["qa", "hr", "employer", "purple"] + list(OPTIONAL))
    assert research.calls["kw"][0]["purpose"] == "prep"
    assert pkg.schema_version == 3 and pkg.kb_version == "2026-09-19"

    # о компании: темы по порядку, источники сверены с поиском
    cp = pkg.company_profile
    assert cp.legal_name == "ООО «Тест-Клиника»" and cp.searches == 7
    assert [s.key for s in cp.sections] == [k for k, _t, _h in cr.TOPICS]
    by = {s.key: s for s in cp.sections}
    assert by["scale"].verified and by["scale"].sources == ["https://www.rusprofile.ru/id/1"]
    assert by["owners"].found and not by["owners"].verified and by["owners"].sources == []
    assert not by["finance"].found and not by["management"].found
    assert by["it"].verified                                    # слэш в конце адреса не мешает
    assert [s.title for s in cp.sources] == ["Rusprofile", "TAdviser: МИС"]

    # справка о компании ушла туда, где уместна
    for stage in ("qa", "employer", "presentation", "team", "improve"):
        assert "Сеть клиник в Москве" in fake.calls["prompts"][stage], stage
    assert "Сеть клиник в Москве" not in fake.calls["prompts"]["hr"]
    assert "Основатель владеет 100%. [не подтверждено источником]" in fake.calls["prompts"]["qa"]

    # «понимание + опыт»: lead нормализован, пустые вопросы отброшены
    assert [q.lead for q in pkg.qa] == ["опыт", "понимание", "опыт"]  # понимание без текста → опыт
    assert pkg.qa[1].understanding.startswith("Kafka")
    assert pkg.hr_qa[0].severity == "hr" and pkg.hr_qa[0].understanding == "Ищу масштаб."
    assert pkg.employer_questions[1].question.startswith("Есть ли внутренний")
    assert pkg.purple_rounds[0].improved_answer
    assert pkg.qa_sources and pkg.hr_sources and pkg.employer_sources

    # рассказ о себе на 3 минуты и 100 дней
    pr = pkg.presentation
    assert pr.who == "Я CIO…" and pr.seeking.startswith("Ищу роль")
    assert pr.short == "Я CIO…\n\nПуть через УРАЛХИМ и МВПС…\n\nИщу роль, где ИТ — часть стратегии…"
    assert pr.sources == ["beelinenow.ru"]
    assert pkg.hundred_days.block3 == "Карта." and any("источник 20" in s for s in pkg.hundred_days.sources)
    assert "Директор по информационным технологиям" in fake.calls["prompts"]["presentation"]  # целевые роли

    # структура и персонал
    tm = pkg.team
    assert tm.estimate.startswith("Оценка") and [u.name for u in tm.units] == ["Поддержка клиник"]
    assert tm.clarify == ["Сколько людей в ИТ сейчас?"]
    assert tm.structure_qa[0].severity == "team" and tm.structure_qa[0].lead == "понимание"
    assert tm.people_qa[0].severity == "people" and tm.people_qa[0].lead == "опыт"
    assert any("S4" in s for s in tm.sources) and all("выдуманный" not in s for s in tm.sources)

    # истории, повестка, «что бы вы улучшили»
    assert [s.kind for s in pkg.stories] == KINDS and pkg.stories_origin == "каркасы из резюме"
    assert [a.topic for a in pkg.agenda][0] == "Информационная безопасность"
    assert len(pkg.blitz) == 8 and pkg.key_numbers == ["1", "2", "3", "4", "5"]
    personal = [d for d in pkg.dont_say if d.personal]
    assert len(personal) == 1 and len([d for d in pkg.dont_say if not d.personal]) >= 10
    im = pkg.improvements
    assert [i.basis for i in im.items] == ["вакансия", "отрасль"]
    assert any("S5" in x for x in im.sources) and all("выдуманный" not in x for x in im.sources)

    # артефакты
    md = (tmp_path / "hh_42.md").read_text(encoding="utf-8")
    for fragment in ["## О компании", "### Масштаб и география", "https://www.rusprofile.ru/id/1",
                     "_(не подтверждено источником)_", "**Как использовать на интервью:**",
                     "## Рассказ о себе (3 минуты)", "### Что ищу",
                     "**Моё понимание.** Kafka", "**Мой опыт.** Цифровой советчик",
                     "## Структура и персонал", "### Управление подчинёнными", "**Оценка ИТ-структуры",
                     "Истории и управленческие кейсы", "План первых 100 дней", "Повестка 2026",
                     "Чего не говорить", "Шпаргалка: 10 минут до звонка", "**О компании:**",
                     "«Что бы вы улучшили у нас?»", "Purple Team", "_Источники:"]:
        assert fragment in md, fragment
    for gone in ["Как проходит процесс", "## Козыри под эту вакансию", "## Болевые зоны", "**Козыри:**"]:
        assert gone not in md, gone
    assert md.index("## О компании") < md.index("## Рассказ о себе") < md.index("## Вопросы интервьюера")
    assert md.index("**Моё понимание.** Kafka") < md.index("**Мой опыт.** Цифровой советчик")
    assert md.index("**Мой опыт.** Завершил") < md.index("**Моё понимание.** Ищу масштаб")  # ведёт опыт

    loaded = ip.load_saved_prep("hh_42")
    assert loaded is not None and loaded.schema_version == 3
    assert loaded.company_profile.sections[0].verified and loaded.company_profile.talking_points
    assert loaded.team.people_qa[0].lead == "опыт" and loaded.team.units[0].size == "10–14"
    assert loaded.presentation.seeking == pr.seeking
    assert loaded.qa[1].understanding == pkg.qa[1].understanding
    assert loaded.improvements.items[0].area == "Данные для планирования"


def test_prep_calls_are_tagged_prep_purpose(monkeypatch):
    from core import llm
    seen = {}

    def fake(system, prompt, **kw):
        seen.update(kw)
        return {}
    monkeypatch.setattr(llm, "call_json", fake)
    ip._call_llm("sk-test", "s", "p", max_tokens=123)
    assert seen["purpose"] == "prep" and seen["max_tokens"] == 123 and seen["banned_substrings"] == [", а не "]
    assert seen["cached_prefix"] is None
    ip._call_llm("sk-test", "s", "p", materials="РЕЗЮМЕ…")
    assert seen["cached_prefix"] == "РЕЗЮМЕ…"


def test_build_prep_no_key(monkeypatch, tmp_path):
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(ip, "_get_api_key", lambda: "")
    pkg = ip.build_prep(vacancy_text="v", package_id="hh_1", resume_text="r")
    assert pkg.error and "OPENAI_API_KEY" in pkg.error


def test_build_prep_empty_qa_is_error(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm(override={"qa": {"qa": []}}))
    pkg = ip.build_prep(vacancy_text="v", package_id="hh_2", resume_text="r")
    assert pkg.error
    assert not (tmp_path / "hh_2.json").exists()


def test_optional_stage_failure_keeps_package(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm(fail={"stories"}))
    pkg = ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_3",
                        resume_text="r", stories_text="")
    assert not pkg.error
    assert len(pkg.stage_errors) == 1 and "истории" in pkg.stage_errors[0]
    assert pkg.stories == []
    assert pkg.presentation.who and pkg.team.people_qa and pkg.blitz   # соседние этапы собрались
    md = (tmp_path / "hh_3.md").read_text(encoding="utf-8")
    assert "Часть разделов не собралась" in md


def test_company_research_failure_is_not_fatal(monkeypatch, tmp_path):
    fake = _mock_llm()
    _setup(monkeypatch, tmp_path, fake, research=_mock_research(fail=True))
    pkg = ip.build_prep(vacancy_text="v", title="CIO", company="Тест", package_id="hh_15",
                        resume_text="r", stories_text="")
    assert not pkg.error and pkg.qa
    assert pkg.stage_errors == ["о компании: поиск недоступен"]
    assert pkg.company_profile.empty
    assert "справка о компании не собрана" in fake.calls["prompts"]["qa"]
    assert ip.present_stages(pkg) == {k for k, _ in ip.STAGES} - {"company"}


def test_optional_stages_run_in_parallel(monkeypatch, tmp_path):
    barrier = threading.Barrier(3, timeout=5)

    def hook(stage):
        if stage in ("presentation", "team", "stories"):   # первые три этапа идут одновременно
            barrier.wait()
    monkeypatch.setattr(ip, "PARALLEL_STAGES", 3)
    _setup(monkeypatch, tmp_path, _mock_llm(hook=hook))
    pkg = ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_16", resume_text="r", stories_text="")
    assert not pkg.stage_errors and pkg.stories and pkg.team.estimate and pkg.presentation.who


def test_stage_errors_sorted_by_plan_order(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm(fail={"improve", "presentation", "agenda"}))
    pkg = ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_17", resume_text="r", stories_text="")
    assert [e.split(":")[0] for e in pkg.stage_errors] == [
        "рассказ о себе и 100 дней", "повестка 2026, блиц, «чего не говорить»", "«что бы вы улучшили у нас»"]


def test_stories_file_drives_origin(monkeypatch, tmp_path):
    fake = _mock_llm()
    _setup(monkeypatch, tmp_path, fake)
    stories = "## Конфликт 1\nВ 2024 году спорил с CFO о бюджете MES, договорились о пилоте на одном заводе."
    pkg = ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_4",
                        resume_text="r", stories_text=stories)
    assert pkg.stories_origin == "файл историй"
    assert "спорил с CFO о бюджете MES" in fake.calls["prompts"]["stories"]


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
    assert pkg.company_profile.empty and pkg.team.estimate == "" and pkg.presentation.who == ""
    assert pkg.stories == [] and pkg.dont_say == [] and pkg.improvements.items == []
    assert pkg.qa[0].question == "Вопрос?" and pkg.qa[0].lead == ""
    assert ip.answer_parts(pkg.qa[0]) == [("", "Ответ.")]       # старый ответ — без подписи


def _v2_package(tmp_path, pid="hh_18"):
    old = {
        "package_id": pid, "vacancy_title": "CIO", "company": "Тест", "vacancy_url": "",
        "interviewer_profile": "Профиль.", "schema_version": 2,
        "qa": [{"source": "s", "question": "Вопрос?", "answer": "Ответ.", "severity": "warn"}],
        "hr_qa": [{"question": "Почему?", "answer": "Потому.", "severity": "hr"}],
        "employer_questions": [{"question": "Мандат?", "why": "w"}],
        "purple_rounds": [{"attack": "a", "defense": "d", "verdict": "v", "improved_answer": "i"}],
        "process": {"basis": "typical", "stages": [{"stage": "Скрининг", "who": "HRD"}]},
        "presentation": {"short": "Самопрезентация 1–3 минуты.", "long": "Длинная.", "scope_line": "Руками…"},
        "hundred_days": {"block1": "Аудит.", "pitch": "За минуту."},
        "stories": [{"kind": "failure", "title": "t"}], "agenda": [{"topic": "ИБ"}],
        "improvements": {"items": [{"area": "a", "hypothesis": "h"}]},
        "top_risks": ["риск"], "top_trumps": ["козырь"], "generated_at": "2026-10-20T14:54:04", "error": "",
    }
    (tmp_path / f"{pid}.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")


def test_old_v2_package_resume_adds_company_and_team(monkeypatch, tmp_path):
    fake = _mock_llm()
    research = _setup(monkeypatch, tmp_path, fake)
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "r")
    _v2_package(tmp_path)
    pkg = ip.load_saved_prep("hh_18")
    assert pkg.schema_version == 2 and pkg.presentation.short.startswith("Самопрезентация")
    assert ip.present_stages(pkg) == {k for k, _ in ip.STAGES} - {"company", "team"}

    out = ip.resume_prep("hh_18", vacancy_text="v", stories_text="")
    assert research.calls["n"] == 1 and fake.calls["stages"] == ["team"]
    assert "Сеть клиник в Москве" in fake.calls["prompts"]["team"]
    assert not out.company_profile.empty and out.team.people_qa and not out.stage_errors
    assert out.presentation.short.startswith("Самопрезентация")     # старый текст не тронут
    md = (tmp_path / "hh_18.md").read_text(encoding="utf-8")
    assert "## О компании" in md and "## Структура и персонал" in md
    assert "Шпаргалка: 10 минут до звонка" in md and "**О себе:** Самопрезентация" in md


def test_build_cheatsheet_from_package():
    pkg = PrepPackage(
        package_id="hh_6", vacancy_title="CIO", company="Тест",
        top_trumps=["a", "b", "c", "d"], key_numbers=["1", "2"],
        qa=[PrepQA(question="Риск?", answer="Ответ на риск.", severity="risk")],
        employer_questions=[ip.EmployerQuestion(question=f"В{i}?", why="") for i in range(4)],
        purple_rounds=[ip.PurpleRound(attack="Атака", defense="Защита", improved_answer="Отточено")],
        company_profile=cr.CompanyProfile(summary="Сеть клиник.", talking_points=[f"t{i}" for i in range(6)]),
        presentation=ip.Presentation(who="Кто", experience="Опыт", seeking="Ищу", short="Кто\n\nОпыт\n\nИщу"),
        dont_say=[ip.DontSayItem(text="общее", personal=False), ip.DontSayItem(text="личное", personal=True)],
        blitz=[ip.BlitzQA(question=f"q{i}", answer="a") for i in range(7)],
        hundred_days=ip.HundredDays(pitch="За минуту"),
        improvements=ip.Improvements(items=[ip.Improvement(phrasing="п0"), ip.Improvement(hypothesis="г1"),
                                            ip.Improvement(), ip.Improvement(phrasing="п3"),
                                            ip.Improvement(phrasing="п4")]),
    )
    cs = ip.build_cheatsheet(pkg)
    assert cs.company_facts == ["t0", "t1", "t2", "t3"]
    assert cs.presentation_parts == [("Кто я", "Кто"), ("Опыт и достижения", "Опыт"), ("Что ищу", "Ищу")]
    assert cs.presentation_short == ""
    assert cs.risk_answers == [("Атака", "Отточено"), ("Риск?", "Ответ на риск.")]  # добор из qa
    assert cs.employer_questions == ["В0?", "В1?", "В2?"]
    assert cs.dont_say[0] == "личное"                       # личные — первыми
    assert len(cs.blitz) == 5 and cs.hundred_days_pitch == "За минуту"
    assert cs.improve == ["п0", "г1", "п3"]                # фраза, иначе гипотеза; пустые пропущены
    assert not hasattr(cs, "trumps") and not hasattr(cs, "stages")

    old = PrepPackage(presentation=ip.Presentation(short="Самопрезентация."),
                      company_profile=cr.CompanyProfile(summary="Сеть клиник."))
    cs_old = ip.build_cheatsheet(old)
    assert cs_old.presentation_parts == [] and cs_old.presentation_short == "Самопрезентация."
    assert cs_old.company_facts == ["Сеть клиник."]          # без пунктов — краткая справка


def test_answer_parts_order():
    q = PrepQA(question="?", understanding="Как это делается.", answer="Мой пример.", lead="понимание")
    assert ip.answer_parts(q) == [("Моё понимание", "Как это делается."), ("Мой опыт", "Мой пример.")]
    q.lead = "опыт"
    assert ip.answer_parts(q) == [("Мой опыт", "Мой пример."), ("Моё понимание", "Как это делается.")]
    q.answer = ""
    assert ip.answer_parts(q) == [("Моё понимание", "Как это делается.")]
    assert ip._norm_lead("Понимание (в резюме пробел), опыт смежный") == "понимание"
    assert ip._norm_lead("опыт + понимание") == "опыт" and ip._norm_lead("") == ""


def test_ask_in_block_persists_and_deletes(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm())
    ip.build_prep(vacancy_text="v", title="CIO", company="Тест", package_id="hh_7",
                  resume_text="r", stories_text="")
    seen = {}

    def fake(api_key, system, prompt, max_tokens=4000, **kw):
        seen["system"], seen["prompt"] = system, prompt
        return {"answer": "Через матричное управление.", "note": "уточнить численность"}
    monkeypatch.setattr(ip, "_call_llm", fake)
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "резюме")

    item = ip.ask_in_block("hh_7", "qa", "А если спросят про 100+?", vacancy_text="Ищем CIO")
    assert item.block == "qa" and item.answer.startswith("Через") and item.note == "уточнить численность"
    assert "Вопросы по опыту" in seen["system"] and "интервьюер-наставник" in seen["system"]
    assert "МОЁ ПОНИМАНИЕ + МОЙ ОПЫТ" in seen["system"]
    assert "Как считали 99,9%?" in seen["prompt"]          # контекст раздела попал в промпт
    assert "Ищем CIO" in seen["prompt"]

    ip.ask_in_block("hh_7", "purple", "Вы не устали?", vacancy_text="")
    assert "Вы никогда не управляли 100+." in seen["prompt"]   # контекст спарринга
    ip.ask_in_block("hh_7", "team", "Увольняли руководителя?", vacancy_text="")
    assert "Поддержка клиник (10–14)" in seen["prompt"] and "Как сократите ИТ на 20%?" in seen["prompt"]
    ip.ask_in_block("hh_7", "presentation", "Короче", vacancy_text="")
    assert "Что ищу: Ищу роль" in seen["prompt"]
    ip.ask_in_block("hh_7", "qa", "Ещё вопрос", vacancy_text="")
    assert "А если спросят про 100+?" in seen["prompt"]        # история раздела для связности

    loaded = ip.load_saved_prep("hh_7")
    assert [x.block for x in loaded.block_qa] == ["qa", "purple", "team", "presentation", "qa"]
    md = (tmp_path / "hh_7.md").read_text(encoding="utf-8")
    assert md.count("### Ваши вопросы к ИИ") == 4 and "Увольняли руководителя?" in md

    assert ip.delete_block_qa("hh_7", "qa", 0) is True
    assert [x.question for x in ip.load_saved_prep("hh_7").block_qa if x.block == "qa"] == ["Ещё вопрос"]
    assert ip.delete_block_qa("hh_7", "qa", 5) is False

    with pytest.raises(ValueError):
        ip.ask_in_block("hh_7", "unknown", "?")
    assert ip.ask_in_block("hh_7", "qa", "   ").question == ""   # пустой вопрос не вызывает модель


def test_ask_in_company_block_uses_web_search(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm())
    ip.build_prep(vacancy_text="v", title="CIO", company="Тест", package_id="hh_19",
                  resume_text="r", stories_text="")
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "резюме")

    def no_llm(*a, **k):
        raise AssertionError("раздел «О компании» отвечает через веб-поиск")
    monkeypatch.setattr(ip, "_call_llm", no_llm)
    research = _mock_research(ResearchResult(
        data={"answer": "ИТ руководит Иванов (2025).", "note": "",
              "sources": ["https://tadviser.ru/a/1", "https://fake.example/x"]},
        sources=[{"url": "https://tadviser.ru/a/1", "title": "TAdviser"}], searches=2))
    monkeypatch.setattr(cr, "_call_research", research)

    item = ip.ask_in_block("hh_19", "company", "Кто руководит ИТ?", vacancy_text="v")
    assert item.answer.startswith("ИТ руководит Иванов")
    assert item.answer.endswith("Источники: https://tadviser.ru/a/1")       # выдуманный адрес отброшен
    assert research.calls["kw"][0]["max_searches"] == 3
    assert "Сеть клиник в Москве" in research.calls["prompts"][0]        # справка — контекст раздела
    assert '"sources"' in research.calls["prompts"][0]


def test_answer_user_question_persists(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm())
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "резюме")
    ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_9", resume_text="р", stories_text="")

    seen = {}

    def fake(api_key, system, prompt, max_tokens=4000, **kw):
        seen["system"] = system
        seen["prompt"] = prompt
        return {"lead": "понимание", "understanding": "Так это строят.", "answer": "Отвечаю на фактах.", "note": ""}
    monkeypatch.setattr(ip, "_call_llm", fake)
    item = ip.answer_user_question("hh_9", "Почему вы?")
    assert item.answer == "Отвечаю на фактах." and item.understanding == "Так это строят."
    assert item.lead == "понимание" and item.severity == "user"
    assert "МОЁ ПОНИМАНИЕ + МОЙ ОПЫТ" in seen["system"]
    assert ip._COMPOUND_ANSWER_RULE in seen["system"]
    assert "Сеть клиник в Москве" in seen["prompt"]
    assert "ЧИСЛОВЫЕ ОРИЕНТИРЫ" in seen["prompt"]
    assert "подходящих проверенных ориентиров нет" in seen["prompt"]

    loaded = ip.load_saved_prep("hh_9")
    assert len(loaded.user_qa) == 1 and loaded.user_qa[0].question == "Почему вы?"
    assert loaded.team.estimate                              # новые блоки пережили пересохранение
    md = (tmp_path / "hh_9.md").read_text(encoding="utf-8")
    assert "спрошено у двойника" in md and "**Моё понимание.** Так это строят." in md


def test_compound_block_answer_keeps_structure_and_company_context(monkeypatch, tmp_path):
    client, _webapp = _client(monkeypatch, tmp_path)
    _setup(monkeypatch, tmp_path, _mock_llm())
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "Резюме кандидата")
    pkg = PrepPackage(package_id="hh_301", vacancy_title="CIO", company="Тест-Клиника",
                      company_profile=cr.CompanyProfile(summary="Сеть клиник; выручка за 2024 год известна."))
    ip._save(pkg)
    monkeypatch.setattr(ip.kb, "quantitative_context", lambda question, context: "NUMERIC_TEST_REFERENCE")
    text = ("Сначала уточню период и состав бюджета. Для разбора приму годовой бюджет.\n\n"
            "1. Отраслевые ориентиры\nСначала сопоставлю состав расходов.\n\n"
            "2. Проекты и эксплуатация\nПроверю фактический эффект.\n\n"
            "3. Структура затрат внутри ИТ\nПроверю ФОТ вместе с внешними трудозатратами.\n\n"
            "4. Рыночность стоимости\nСравню условия предложений.\n\n"
            "5. Вывод\n300 млн — условный пример. <script>unsafe()</script>")

    def fake(key, system, prompt, **kwargs):
        assert ip._COMPOUND_ANSWER_RULE in system
        assert "выручка за 2024 год" in prompt
        assert "300 млн" in prompt
        assert "NUMERIC_TEST_REFERENCE" in prompt
        return {"answer": text, "note": "Уточнить период бюджета."}

    monkeypatch.setattr(ip, "_call_llm", fake)
    item = ip.ask_in_block("hh_301", "qa", "Эффективны ли расходы? 300 млн — много или мало?",
                           vacancy_text="Управление ИТ-бюджетом")
    assert item.answer == text
    assert ip.load_saved_prep("hh_301").block_qa[-1].answer == text
    markdown = (tmp_path / "hh_301.md").read_text(encoding="utf-8")
    assert "\n\n1. Отраслевые ориентиры\n" in markdown
    page = client.get("/prep/301")
    assert page.status_code == 200
    assert "\n\n2. Проекты и эксплуатация\n" in page.text
    assert "Сначала уточню период и состав бюджета" in page.text
    assert "&lt;script&gt;unsafe()&lt;/script&gt;" in page.text
    assert "<script>unsafe()</script>" not in page.text


# ---------------------------------------------------------------------------
# Маршруты
# ---------------------------------------------------------------------------

def _client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import web.app as webapp
    from agents import vacancy_store as vs
    monkeypatch.setattr(vs, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(ip, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(prep_jobs, "_JOBS", {})
    return TestClient(webapp.app), webapp


def test_prep_route_cold_path(monkeypatch, tmp_path):
    client, webapp = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        webapp.hh_api, "fetch_vacancy_data",
        lambda vid: {"name": "CIO", "employer": "Тест", "description": "текст",
                     "alternate_url": "https://hh.ru/vacancy/7"},
    )
    events = []

    def fake_build(**kw):
        kw["progress"]("company", "start"); kw["progress"]("company", "ok")
        events.append(kw["package_id"])
        pkg = PrepPackage(package_id="hh_7", vacancy_title="CIO", interviewer_profile="Профиль.",
                          qa=[PrepQA(question="Вопрос?", answer="Ответ.", severity="warn")])
        ip._save(pkg)
        return pkg
    monkeypatch.setattr(ip, "build_prep", fake_build)

    # холодный вызов запускает фоновую сборку и уводит на страницу прогресса
    resp = client.get("/prep/7", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/prep/7"
    job = prep_jobs.wait("hh_7")
    assert job is not None and job.done and not job.error and events == ["hh_7"]
    assert [s.status for s in job.stages][:2] == ["ok", "skip"]  # ресёрч отчитался, остальные пропущены

    resp = client.get("/prep/7")
    assert resp.status_code == 200
    assert "Вопрос?" in resp.text
    assert "собран до обновления 21.10.2026" in resp.text      # старая схема → подсказка
    assert 'action="/prep/7/resume"' in resp.text               # новые разделы можно дособрать
    assert client.get("/prep/7/status").json()["done"] is True


def test_prep_progress_page_and_status(monkeypatch, tmp_path):
    client, webapp = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(webapp.hh_api, "fetch_vacancy_data",
                        lambda vid: {"name": "CIO", "employer": "Тест", "description": "текст"})
    gate = threading.Event()

    def slow_build(**kw):
        kw["progress"]("company", "start"); kw["progress"]("company", "ok"); kw["progress"]("qa", "start")
        gate.wait(5)
        raise RuntimeError("обрыв сети")
    monkeypatch.setattr(ip, "build_prep", slow_build)

    client.get("/prep/11", follow_redirects=False)
    page = client.get("/prep/11")
    assert page.status_code == 200 and 'id="progress"' in page.text and "Собираем пакет" in page.text
    assert "ресёрч компании с веб-поиском" in page.text
    st = client.get("/prep/11/status").json()
    assert st["running"] and st["stages"][0]["status"] == "ok" and st["stages"][1]["status"] == "running"
    assert client.get("/prep/11?regenerate=true").status_code == 200   # вторую сборку не запускает
    assert len([t for t in threading.enumerate() if t.name == "prep-hh_11"]) == 1

    gate.set()
    job = prep_jobs.wait("hh_11")
    assert job.done and "обрыв сети" in job.error
    assert [s.status for s in job.stages][:3] == ["ok", "fail", "skip"]
    page = client.get("/prep/11")          # упавшая сборка не перезапускается сама
    assert "обрыв сети" in page.text and "собрать заново" in page.text
    assert client.get("/prep/11/status").json()["done"] is True


def test_build_prep_reports_progress(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm(fail={"stories"}))
    events = []
    lock = threading.Lock()

    def progress(k, s, d=""):
        with lock:
            events.append((k, s))
    ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_12", resume_text="r",
                  stories_text="", progress=progress)
    starts = [k for k, s in events if s == "start"]
    assert starts[:5] == ["company", "qa", "hr", "employer", "purple"]   # последовательно
    assert set(starts[5:]) == OPTIONAL and len(starts) == len(ip.STAGES)  # параллельно, порядок любой
    assert [s for k, s in events if k == "stories"] == ["start", "fail"]
    assert all(s == "ok" for k, s in events if s != "start" and k != "stories")


def test_resume_prep_runs_only_missing_stages(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, _mock_llm(fail={"stories"}))          # истории упали
    pkg = ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_13", resume_text="r", stories_text="")
    assert pkg.stage_errors and not pkg.stories
    assert ip.present_stages(pkg) == {k for k, _ in ip.STAGES} - {"stories"}

    fake = _mock_llm()
    research = _mock_research()
    monkeypatch.setattr(ip, "_call_llm", fake)
    monkeypatch.setattr(cr, "_call_research", research)
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "r")
    events = []
    out = ip.resume_prep("hh_13", vacancy_text="v", stories_text="", progress=lambda k, s, d="": events.append((k, s)))
    assert fake.calls["stages"] == ["stories"] and research.calls["n"] == 0
    assert events == [("stories", "start"), ("stories", "ok")]
    assert out.stage_errors == [] and [s.kind for s in out.stories] == KINDS
    assert ip.load_saved_prep("hh_13").stories                      # сохранено
    assert sum(1 for d in out.dont_say if not d.personal) >= 10   # общий чек-лист не задвоился
    assert ip.resume_prep("hh_nope", "v") is None


def test_resume_route(monkeypatch, tmp_path):
    client, _webapp = _client(monkeypatch, tmp_path)
    _setup(monkeypatch, tmp_path, _mock_llm(fail={"stories"}))
    ip.build_prep(vacancy_text="v", title="CIO", package_id="hh_14", resume_text="r", stories_text="")
    page = client.get("/prep/14")
    assert 'action="/prep/14/resume"' in page.text and "Дособрать упавшие этапы" in page.text
    assert "собран до обновления" not in page.text

    monkeypatch.setattr(ip, "_call_llm", _mock_llm())
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "r")
    resp = client.post("/prep/14/resume", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/prep/14"
    job = prep_jobs.wait("hh_14")
    assert job.kind == "resume" and job.done and not job.error
    assert {s.key: s.status for s in job.stages}["stories"] == "ok"
    assert {s.key: s.detail for s in job.stages}["qa"] == "уже собран"
    assert "Провальный проект" in client.get("/prep/14").text
    assert client.post("/prep/99/resume", follow_redirects=False).status_code == 404


def test_prep_route_renders_v3_sections(monkeypatch, tmp_path):
    client, _webapp = _client(monkeypatch, tmp_path)
    _setup(monkeypatch, tmp_path, _mock_llm())
    ip.build_prep(vacancy_text="v", title="CIO", company="Тест", package_id="hh_8",
                  resume_text="r", stories_text="")
    resp = client.get("/prep/8")
    assert resp.status_code == 200
    text = resp.text
    for fragment in ['id="company"', "Масштаб и география", ">rusprofile.ru</a>", ">tadviser.ru</a>",
                     "не подтверждено", "Как использовать на интервью", "Что выяснить на встрече",
                     'id="presentation"', "3 · Что ищу и куда хочу двигаться", "Ищу роль, где ИТ",
                     'id="team"', "Оценка ИТ-структуры под вакансию", "Поддержка клиник",
                     "Управление подчинёнными", "Ваш сотрудник саботирует",
                     "<b>Моё понимание.</b> Kafka", 'class="lead-tag"',
                     "Провальный проект", "каркас из резюме", "Повестка 2026",
                     "лично вам", "/prep/8/cheatsheet", "/prep/8?regenerate=true",
                     'data-target="company"', 'data-target="team"', 'data-target="cheat"',
                     "classList.toggle('active'", 'data-target="improve"', "«Что бы вы улучшили у нас?»",
                     'class="basis vac"', "Вижу в описании единую отчётность", "~1–2 мин, с веб-поиском"]:
        assert fragment in text, fragment
    for gone in ['data-target="process"', 'data-target="profile"', "Козыри под вакансию",
                 "Как проходит процесс", ">Болевые зоны</h3>", "собран до обновления"]:
        assert gone not in text, gone
    # ссылки источников разделены пробелом, колонки не растягиваются содержимым:
    # без этого ряд адресов был одним «словом» и сетка вылезала за поля (21.10)
    assert ">rusprofile.ru</a> " in text and "repeat(2,minmax(0,1fr))" in text
    # порядок: о компании → о себе → вопросы → HR → структура и персонал → истории
    order = [text.index(f'id="{x}"') for x in ("company", "presentation", "qa", "hr", "team", "stories")]
    assert order == sorted(order)
    # «понимание» идёт первым, если ведёт оно
    assert text.index("<b>Моё понимание.</b> Kafka") < text.index("<b>Мой опыт.</b> Цифровой советчик")
    # скрипт подсветки должен идти после всех блоков, иначе не найдёт их (приёмка 21.09)
    assert text.index('id="dontsay"') < text.index('id="cheat"') < text.index("classList.toggle('active'")

    cheat = client.get("/prep/8/cheatsheet")
    assert cheat.status_code == 200
    for fragment in ["10 минут до звонка", "О компании · что упомянуть", "40 клиник — поддержка",
                     "Рассказ о себе · 3 минуты", "Я CIO…", "Ищу роль", "Не занижать масштаб",
                     "Если спросят «что бы вы улучшили»", "Вижу в описании"]:
        assert fragment in cheat.text, fragment
    assert "Козыри" not in cheat.text and "Этапы · кто передо мной" not in cheat.text

    # окошки «Спросить ИИ» в блоках с коммуникацией
    for block in ["company", "presentation", "qa", "hr", "team", "stories", "days100", "improve",
                  "agenda", "blitz", "employer", "purple"]:
        assert f'action="/prep/8/ask/{block}"' in text, block
    assert 'action="/prep/8/ask/process"' not in text


def test_prep_ask_block_route(monkeypatch, tmp_path):
    client, _webapp = _client(monkeypatch, tmp_path)
    _setup(monkeypatch, tmp_path, _mock_llm())
    ip.build_prep(vacancy_text="v", title="CIO", company="Тест", package_id="hh_9",
                  resume_text="r", stories_text="")
    monkeypatch.setattr(ip, "_call_llm", lambda *a, **k: {"answer": "Ответ ИИ в блице.", "note": ""})
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "резюме")

    resp = client.post("/prep/9/ask/blitz", data={"question": "Что такое RTO?"}, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/prep/9#blitz"
    page = client.get("/prep/9").text
    assert "Что такое RTO?" in page and "Ответ ИИ в блице." in page
    assert 'action="/prep/9/ask/blitz/delete"' in page

    resp = client.post("/prep/9/ask/blitz/delete", data={"idx": "0"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "Ответ ИИ в блице." not in client.get("/prep/9").text

    assert client.post("/prep/9/ask/nope", data={"question": "?"}, follow_redirects=False).status_code == 404


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


def test_second_build_takes_company_from_archive(monkeypatch, tmp_path):
    fake = _mock_llm()
    research = _setup(monkeypatch, tmp_path, fake)
    ip.build_prep(vacancy_text="v", title="CIO", company="ООО «Тест-Клиника»", package_id="hh_20",
                  resume_text="r", stories_text="")
    pkg = ip.build_prep(vacancy_text="v", title="CTO", company="Сеть клиник «Тест-Клиника»",
                        package_id="hh_21", resume_text="r", stories_text="")
    assert research.calls["n"] == 1                               # второй раз — без веб-поиска
    assert pkg.company_profile.from_archive and pkg.company_profile.sections[0].verified
    assert "Сеть клиник в Москве" in fake.calls["prompts"]["qa"]   # справка из архива дошла до этапов


def test_refresh_company_route_bypasses_archive(monkeypatch, tmp_path):
    client, _webapp = _client(monkeypatch, tmp_path)
    research = _setup(monkeypatch, tmp_path, _mock_llm(), research=_mock_research(fail=True))
    ip.build_prep(vacancy_text="v", title="CIO", company="Тест", package_id="hh_22",
                  resume_text="r", stories_text="")
    page = client.get("/prep/22").text
    assert 'action="/prep/22/company/refresh"' not in page        # раздела нет — кнопки тоже
    assert research.calls["n"] == 1

    research2 = _mock_research()
    monkeypatch.setattr(cr, "_call_research", research2)
    resp = client.post("/prep/22/company/refresh", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/prep/22#company"
    assert research2.calls["n"] == 1
    pkg = ip.load_saved_prep("hh_22")
    assert not pkg.company_profile.empty and not pkg.company_profile.from_archive
    assert not any(e.startswith("о компании") for e in pkg.stage_errors)
    page = client.get("/prep/22").text
    assert 'action="/prep/22/company/refresh"' in page and "Обновить ресёрч" in page

    client.post("/prep/22/company/refresh", follow_redirects=False)  # повторно — снова мимо архива
    assert research2.calls["n"] == 2
    monkeypatch.setattr(cr, "_call_research", _mock_research(fail=True))
    assert client.post("/prep/22/company/refresh", follow_redirects=False).status_code == 502
    assert not ip.load_saved_prep("hh_22").company_profile.empty     # сбой не стёр справку
    assert client.post("/prep/99/company/refresh", follow_redirects=False).status_code == 404


def test_resume_and_facts_go_to_one_cached_block(monkeypatch, tmp_path):
    """
    Резюме и факт-база — общий кешируемый блок системы (21.10.2026): во всех
    девяти этапах он один и тот же байт в байт, а в тексте этапов его нет.
    """
    fake = _mock_llm()
    _setup(monkeypatch, tmp_path, fake)
    monkeypatch.setattr(ip, "load_facts", lambda: "Факт: команда 30+.")
    ip.build_prep(vacancy_text="v", title="CIO", company="Тест", package_id="hh_23",
                  resume_text="Резюме-маркер-7f3a", stories_text="")
    mats = fake.calls["materials"]
    assert set(mats) == {"qa", "hr", "employer", "purple"} | OPTIONAL
    assert len(set(mats.values())) == 1                      # один и тот же текст — кеш попадает
    block = next(iter(mats.values()))
    assert block.startswith("МАТЕРИАЛЫ КАНДИДАТА") and "Резюме-маркер-7f3a" in block
    assert "Факт: команда 30+." in block
    for stage, prompt in fake.calls["prompts"].items():
        assert "РЕЗЮМЕ КАНДИДАТА" not in prompt and "маркер-7f3a" not in prompt, stage

    seen = {}

    def ask(api_key, system, prompt, max_tokens=4000, **kw):
        seen.update(kw, prompt=prompt)
        return {"answer": "a", "note": ""}
    monkeypatch.setattr(ip, "_call_llm", ask)
    monkeypatch.setattr(ip, "load_canonical_resume", lambda: "Резюме-маркер-7f3a")
    ip.ask_in_block("hh_23", "qa", "Вопрос?", vacancy_text="v")
    assert seen["materials"] == block and "маркер-7f3a" not in seen["prompt"]   # окошки читают тот же кеш
    ip.answer_user_question("hh_23", "Почему вы?")
    assert seen["materials"] == block
