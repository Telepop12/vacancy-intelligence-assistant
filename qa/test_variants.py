"""
pytest: Resume Variants layer — offline (LLM and file IO mocked/isolated).
"""
import json

import pytest

from agents import resume_variants as rv
from agents.resume_variants import PositionAccent, ResumeVariant


@pytest.mark.no_llm
def test_config_has_five_variants():
    cfg = rv.load_variants_config()
    assert set(cfg["variants"]) == {"cio", "cto", "cdto", "caio", "universal"}
    for key, vcfg in cfg["variants"].items():
        assert vcfg["name"], key
        assert vcfg["focus"], key
    assert cfg["resume_file"]


@pytest.mark.no_llm
def test_unknown_variant_key():
    v = rv.generate_variant("nonexistent")
    assert v.error
    assert "Неизвестный вариант" in v.error


@pytest.mark.no_llm
def test_render_md_contains_all_sections():
    v = ResumeVariant(
        key="cio",
        name="CIO — классический",
        hh_title="Директор по ИТ (CIO)",
        about="Руководитель ИТ с опытом трансформации.",
        key_skills=["ИТ-стратегия", "ERP"],
        positions=[PositionAccent(company="Компания", period="2020–2024",
                                  title="CIO", bullets=["Построил ИТ-стратегию"])],
        what_changed="Акцент на стратегию.",
        honest_gaps="Мало публичных AI-кейсов.",
        generated_at="2026-07-05T00:00:00",
    )
    md = rv.render_variant_md(v)
    for fragment in [
        "# CIO — классический",
        "Директор по ИТ (CIO)",
        "## Блок «О себе»",
        "- ИТ-стратегия",
        "### Компания · 2020–2024",
        "- Построил ИТ-стратегию",
        "## Честные пробелы",
    ]:
        assert fragment in md, fragment


@pytest.mark.no_llm
def test_generate_and_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(rv, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(rv, "_call_llm", lambda api_key, prompt: {
        "hh_title": "Директор по цифровой трансформации",
        "about": "О себе.",
        "key_skills": ["MDM", "BI"],
        "positions": [
            {"company": "Ф", "period": "2021–2025", "title": "CDTO",
             "bullets": ["Внедрил MDM"]},
        ],
        "what_changed": "Акценты на данные.",
        "honest_gaps": "—",
    })

    v = rv.generate_variant("cdto", resume_text="текст резюме")
    assert not v.error
    assert v.hh_title.startswith("Директор")
    assert (tmp_path / "cdto.json").exists()
    assert (tmp_path / "cdto.md").exists()

    saved = rv.load_saved_variants()
    assert "cdto" in saved
    assert saved["cdto"].key_skills == ["MDM", "BI"]
    assert saved["cdto"].positions[0].company == "Ф"


@pytest.mark.no_llm
def test_generate_without_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(rv, "_get_api_key", lambda: "")
    v = rv.generate_variant("cio", resume_text="текст")
    assert v.error
    assert "Ollama" in v.error
    assert not (tmp_path / "cio.json").exists()


@pytest.mark.no_llm
def test_corrupt_saved_variant_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "OUTPUT_DIR", tmp_path)
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert rv.load_saved_variants() == {}


_CLEAN_DATA = {
    "hh_title": "CIO", "about": "О себе.", "key_skills": ["ERP"],
    "positions": [{"company": "К", "period": "2020", "title": "CIO",
                   "bullets": ["Выстроил ИТ-стратегию"]}],
    "what_changed": "—", "honest_gaps": "—",
}


@pytest.mark.no_llm
def test_arrow_chain_triggers_retry(monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(rv, "_get_api_key", lambda: "sk-test")
    dirty = dict(_CLEAN_DATA, about="аудит → стратегия → бюджет")
    calls = []

    def fake_llm(api_key, prompt):
        calls.append(prompt)
        return dirty if len(calls) == 1 else _CLEAN_DATA

    monkeypatch.setattr(rv, "_call_llm", fake_llm)
    v = rv.generate_variant("cio", resume_text="текст")
    assert not v.error
    assert len(calls) == 2
    assert "→" in calls[1]          # retry-фидбек называет пойманный паттерн
    assert v.about == "О себе."


@pytest.mark.no_llm
def test_published_version_feeds_prompt_and_date(monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(rv, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(
        rv, "load_published",
        lambda vcfg: ("ОПУБЛИКОВАННЫЙ ТЕКСТ РЕЗЮМЕ HH", "2026-08-05"),
    )
    prompts = []
    monkeypatch.setattr(
        rv, "_call_llm",
        lambda api_key, prompt: prompts.append(prompt) or _CLEAN_DATA,
    )
    v = rv.generate_variant("cio", resume_text="канон")
    assert not v.error
    assert v.published_at == "2026-08-05"
    assert "ОПУБЛИКОВАННЫЙ ТЕКСТ РЕЗЮМЕ HH" in prompts[0]
    assert "РЕЖИМ РЕДАКТОРА" in prompts[0]
    md = (tmp_path / "cio.md").read_text(encoding="utf-8")
    assert "hh-версия от 2026-08-05" in md


@pytest.mark.no_llm
def test_no_published_file_keeps_canon_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(rv, "_get_api_key", lambda: "sk-test")
    monkeypatch.setattr(rv, "load_published", lambda vcfg: ("", ""))
    prompts = []
    monkeypatch.setattr(
        rv, "_call_llm",
        lambda api_key, prompt: prompts.append(prompt) or _CLEAN_DATA,
    )
    v = rv.generate_variant("cio", resume_text="канон")
    assert not v.error
    assert v.published_at == ""
    assert "РЕЖИМ РЕДАКТОРА" not in prompts[0]
