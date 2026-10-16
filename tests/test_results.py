"""Tests for the research-results summary, its API endpoint and the page that shows it"""

import json
import re
from pathlib import Path

import pytest

import api_server
from results_summary import MODES, build_summary

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / 'admin-dashboard'


# ---------------------------------------------------------------- the summary

class TestSummary:
    def test_all_four_result_files_are_read(self):
        summary = build_summary()
        assert summary['missing'] == []
        for section in ('detection', 'baseline', 'sweep', 'network'):
            assert summary[section] is not None, section

    def test_figures_match_the_result_files(self):
        """The numbers quoted in the methodology, taken from the files themselves"""
        summary = build_summary()

        detection = summary['detection']
        assert detection['test_frauds'] == 75
        assert detection['metrics']['recall']['value'] == pytest.approx(0.84)
        assert detection['metrics']['precision']['value'] == pytest.approx(0.3877, abs=1e-3)
        low, high = detection['metrics']['precision']['low'], detection['metrics']['precision']['high']
        assert low < detection['metrics']['precision']['value'] < high

        baseline = summary['baseline']['architectures']
        assert baseline['external_batch']['p50_ms'] == pytest.approx(5045, abs=2)
        assert baseline['in_database']['p50_ms'] == pytest.approx(23.2, abs=0.2)
        assert all(a['max_score_difference'] == 0.0 for a in baseline.values())

        point = next(p for p in summary['sweep']['points'] if p['rate_per_s'] == 160 and p['connections'] == 4)
        assert point['architectures']['in_database']['achieved_rate_per_s'] == pytest.approx(132.0, abs=0.5)
        assert point['architectures']['in_database']['saturated'] is True
        assert point['architectures']['external_batch']['saturated'] is False

        network = next(p for p in summary['network']['points'] if p['reads'] == 3 and round(p['round_trip_ms']) == 103)
        assert network['architectures']['application']['p50_ms'] == pytest.approx(467, abs=2)
        assert network['architectures']['in_database']['p50_ms'] == pytest.approx(156, abs=2)

    def test_sweep_and_network_cover_every_architecture_and_point(self):
        summary = build_summary()
        assert len(summary['sweep']['points']) == 10
        assert len(summary['network']['points']) == 10
        for point in summary['sweep']['points'] + summary['network']['points']:
            assert set(point['architectures']) == set(MODES)

    def test_noise_is_reported_not_hidden(self):
        summary = build_summary()
        assert summary['sweep']['runs_total'] == 90
        assert 0 < summary['sweep']['runs_started_busy'] < 90
        assert summary['network']['median_other_programs_cpu_percent'] > 0

    def test_no_machine_identifiers_or_commit_ids_leak(self):
        text = json.dumps(build_summary())
        for forbidden in ('Windows-', 'commit', 'uncommitted', 'C:\\\\', 'Lucky', 'python'):
            assert forbidden not in text, forbidden

    def test_the_summary_is_a_small_fraction_of_the_raw_files(self):
        raw = sum((ROOT / 'results' / name).stat().st_size for name in
                  ('rate_sweep.json', 'network_latency.json', 'architecture_benchmark.json', 'evaluation_metrics.json'))
        assert len(json.dumps(build_summary())) < raw / 5

    def test_missing_files_are_listed_and_do_not_crash(self, tmp_path):
        summary = build_summary(tmp_path)
        assert summary['detection'] is None and summary['sweep'] is None
        assert len(summary['missing']) == 4

    def test_an_unreadable_file_is_treated_as_missing(self, tmp_path):
        (tmp_path / 'rate_sweep.json').write_text('{not json', encoding='utf-8')
        assert 'rate_sweep.json' in build_summary(tmp_path)['missing']


# ---------------------------------------------------------------- the endpoint

class TestEndpoint:
    def test_requires_a_token(self, client):
        assert client.get('/api/research/results').status_code == 401

    def test_returns_the_summary_to_a_logged_in_user(self, client, auth):
        response = client.get('/api/research/results', headers=auth)
        assert response.status_code == 200
        results = response.get_json()['results']
        assert results['missing'] == []
        assert results['baseline']['architectures']['external_batch']['p50_ms'] > 1000

    def test_a_failure_does_not_leak_details(self, client, auth, monkeypatch):
        def explode():
            raise RuntimeError('SECRET-PATH C:\\internal\\results')
        monkeypatch.setattr(api_server, 'build_summary', explode)
        response = client.get('/api/research/results', headers=auth)
        assert response.status_code == 500
        assert 'SECRET-PATH' not in response.get_data(as_text=True)
        assert response.get_json()['error'] == 'Internal server error'


# ---------------------------------------------------------------- the page

class TestPage:
    def test_the_page_code_never_uses_innerhtml(self):
        source = (DASHBOARD / 'results.js').read_text(encoding='utf-8')
        for unsafe in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval('):
            assert unsafe not in source, unsafe

    def test_the_page_sends_the_login_token_and_redirects_without_one(self):
        source = (DASHBOARD / 'results.js').read_text(encoding='utf-8')
        assert 'Authorization' in source and 'fraudAdmin.token' in source
        assert 'index.html' in source

    def test_every_file_the_page_loads_exists(self):
        html = (DASHBOARD / 'results.html').read_text(encoding='utf-8')
        for name in re.findall(r'(?:src|href)="([^"]+)"', html):
            assert (DASHBOARD / name).exists(), name

    def test_every_element_the_script_fills_exists_in_the_page(self):
        html = (DASHBOARD / 'results.html').read_text(encoding='utf-8')
        source = (DASHBOARD / 'results.js').read_text(encoding='utf-8')
        for element_id in set(re.findall(r'getElementById\("([A-Za-z]+)"\)', source)):
            assert f'id="{element_id}"' in html, element_id

    def test_the_main_dashboard_links_to_the_page_and_no_longer_prefills_the_password(self):
        html = (DASHBOARD / 'index.html').read_text(encoding='utf-8')
        assert 'href="results.html"' in html
        password_input = re.search(r'<input[^>]*id="password"[^>]*>', html).group(0)
        assert 'value=' not in password_input
