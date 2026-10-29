"""Additional isolated regressions found during review, 2026-10-29.
Run from the project root:
    py -3.14 -m pytest output/review_2026-10-29/regressions.py -q -p no:cacheprovider
These assert the desired behavior. Five failures reproduce the reviewed bugs.
No real state is written; no model or network calls are made.
"""
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from agents import company_research as cr, hh_search as hs, vacancy_store as vs
from web import app as wa


def test_download_rejects_output_sibling(tmp_path):
    output = tmp_path / 'output'
    output.mkdir()
    sibling = tmp_path / 'output_private'
    sibling.mkdir()
    (sibling / 'private.json').write_text('{"synthetic":true}', encoding='utf8')
    with patch.object(wa, 'OUTPUT_DIR', output):
        client = TestClient(wa.app, raise_server_exceptions=False)
        response = client.get('/output/%2e%2e/output_private/private.json')
    assert response.status_code == 404, 'A file outside output was served'


def test_search_preserves_vacancy_registered_during_fetch(tmp_path):
    def item(profile, data, vid, **kw):
        return hs.TriageItem(hh_id=vid, title=data['name'])

    def fetch(ids):
        hs.register_vacancy(None, {'name': 'Manual vacancy'}, 'm-review')
        return {'12345': {'name': 'Search vacancy', 'description': 'Test'}}, {}, False

    with patch.object(hs, 'STATE_PATH', tmp_path / 'state.json'), \
         patch.object(vs, 'STORE_DIR', tmp_path / 'vacancies'), \
         patch.object(hs, 'make_triage_item', item), \
         patch.object(hs, 'load_search_config', return_value={'queries': ['q'], 'max_new_per_run': 30}), \
         patch.object(hs.hh_api, 'search_vacancy_ids', return_value=['12345']), \
         patch.object(hs.hh_api, 'fetch_vacancies_batch', side_effect=fetch):
        hs.run_search(None)
        assert set(hs._load_state()) == {'12345', 'm-review'}, 'Manual ledger row was lost'


def test_source_verification_rejects_unseen_page_on_seen_domain():
    unseen = 'https://www.rusprofile.ru/id/999999999999999999'
    seen = [{'url': 'https://www.rusprofile.ru/id/1', 'title': 'Another company'}]
    assert cr.verify_urls([unseen], seen) == [], 'Invented page was accepted as verified'


def test_two_manual_vacancies_in_same_second_have_different_ids(tmp_path):
    class SameSecond:
        @staticmethod
        def now():
            return datetime(2026, 10, 29, 12, 34, 56)

    with patch.object(vs, 'STORE_DIR', tmp_path / 'vacancies'), patch.object(vs, 'datetime', SameSecond):
        first = vs.save_vacancy({'name': 'First'})
        second = vs.save_vacancy({'name': 'Second'})
        assert first != second, 'The second vacancy overwrote the first'


def test_two_analyses_in_same_second_keep_both_reports(tmp_path):
    from core.analyzers.rule_based import RuleBasedAnalyzer
    from core.report import save_json
    from main import load_profile
    analysis = RuleBasedAnalyzer().analyze('CIO enterprise transformation', load_profile(ROOT / 'config/candidate_profile.yaml'))
    analysis.analyzed_at = datetime(2026, 10, 29, 12, 34, 56)
    analysis.source_file = 'first.txt'
    first = save_json(analysis, tmp_path)
    analysis.source_file = 'second.txt'
    second = save_json(analysis, tmp_path)
    assert first != second and len(list(tmp_path.glob('*.json'))) == 2, 'The second analysis replaced the first report'
