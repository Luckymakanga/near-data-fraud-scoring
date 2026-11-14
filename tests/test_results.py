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
            if name.startswith('https://'):
                continue  # links out of the application are checked in test_links_out_of_the_page
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

    def test_links_out_of_the_page_open_in_a_new_tab_and_cannot_reach_back(self):
        html = (DASHBOARD / 'results.html').read_text(encoding='utf-8')
        anchors = re.findall(r'<a [^>]*href="https://[^"]+"[^>]*>', html)
        assert anchors, 'the learn-more links are missing'
        for anchor in anchors:
            assert 'target="_blank"' in anchor and 'rel="noopener noreferrer"' in anchor, anchor

    def test_the_page_opens_with_a_short_summary_and_keeps_the_detail_behind_show_links(self):
        html = (DASHBOARD / 'results.html').read_text(encoding='utf-8')
        source = (DASHBOARD / 'results.js').read_text(encoding='utf-8')
        for element_id in ('summaryPanel', 'summaryList', 'summaryVerdict', 'detectionTake', 'baselineTake', 'sweepTake', 'networkTake'):
            assert f'id="{element_id}"' in html and f'getElementById("{element_id}")' in source, element_id
        assert html.count('<details class="more"') >= 6
        assert html.index('id="summaryPanel"') < html.index('id="detectionPanel"')

    def test_no_result_is_typed_into_the_page(self):
        # every figure comes from the result files, so none may be written into the page itself
        html = (DASHBOARD / 'results.html').read_text(encoding='utf-8')
        for panel in ('summaryPanel', 'detectionPanel', 'baselinePanel', 'sweepPanel', 'networkPanel'):
            block = re.search(r'<section[^>]*id="' + panel + r'".*?</section>', html, re.S).group(0)
            visible = re.sub(r'<[^>]+>', ' ', block)
            assert not re.search(r'\d+(?:\.\d+)? ?(?:ms|seconds|per second|%)', visible), panel

    def test_the_verdict_is_worked_out_from_the_data(self):
        import json, shutil, subprocess
        node = shutil.which('node')
        if not node:
            pytest.skip('node is not installed')
        source = (DASHBOARD / 'results.js').read_text(encoding='utf-8')
        start = source.index('function verdictText(results)')
        end = source.index('// Five labelled lines at the top')
        arch = lambda b, d, a, sat=False: {'external_batch': {'p50_ms': b}, 'in_database': {'p50_ms': d, 'saturated': sat}, 'application': {'p50_ms': a, 'saturated': sat}}
        results = {
            'baseline': {'architectures': arch(5000, 23, 23)},
            'sweep': {'points': [{'architectures': arch(5000, 20, 40)}, {'architectures': arch(5000, 30, 60)}, {'architectures': arch(5100, 9000, 15000, True)}]},
            'network': {'points': [{'architectures': arch(5000, 60, 120)}]},
        }
        script = source[start:end] + 'console.log(verdictText(' + json.dumps(results) + '));'
        out = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=30).stdout.strip()
        assert out.startswith('Fastest: scoring inside the database.')
        assert 'in 5 of the 5 conditions' in out
        assert 'slower than both whenever they kept up (4 of 4)' in out
        assert 'could be slower than the batch job' in out
        # with the two reversed the verdict follows the data and does not favour the database
        flipped = {k: v for k, v in results.items()}
        flipped['sweep'] = {'points': [{'architectures': arch(5000, 40, 20)}, {'architectures': arch(5000, 60, 30)}]}
        flipped['network'] = {'points': [{'architectures': arch(5000, 120, 60)}]}
        flipped['baseline'] = {'architectures': arch(5000, 46, 23)}
        script = source[start:end] + 'console.log(verdictText(' + json.dumps(flipped) + '));'
        out = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=30).stdout.strip()
        assert out.startswith('Fastest: scoring in the application.')

# ---------------------------------------------------------------- the research page: what it shows and how

class TestResearchPageContent:
    def source(self):
        return (DASHBOARD / 'results.js').read_text(encoding='utf-8')

    def html(self):
        return (DASHBOARD / 'results.html').read_text(encoding='utf-8')

    def test_the_summary_passes_on_the_mean_latency_and_the_auc_roc_that_are_in_the_files(self):
        summary = build_summary()
        raw = json.loads((ROOT / 'results' / 'architecture_benchmark.json').read_text(encoding='utf-8'))
        for mode, arch in raw['architectures'].items():
            assert summary['baseline']['architectures'][mode]['mean_ms'] == arch['decision_latency_ms']['mean']
        roc = summary['detection']['metrics']['roc_auc']
        assert (round(roc['value'], 3), round(roc['low'], 3), round(roc['high'], 3)) == (0.977, 0.956, 0.995)    # as in Table 11 of the report

    def test_the_figures_the_page_derives_agree_with_the_report(self):
        """Table 12 of the report: the mean, the 95th percentile and the share of one core"""
        baseline = build_summary()['baseline']
        a = baseline['architectures']
        assert [round(a[m]['mean_ms']) for m in ('in_database', 'application')] == [27, 27]
        assert round(a['external_batch']['mean_ms'] / 1000, 1) == 5.0
        assert [round(a[m]['p95_ms']) for m in ('in_database', 'application')] == [50, 49]
        share = {m: round(a[m]['cpu_s_per_1000'] * baseline['rate_per_s'] / 10, 1) for m in a}      # seconds per 1,000 x rate / 1,000, as a percentage
        assert share == {'external_batch': 1.5, 'in_database': 23.7, 'application': 23.6}

    def test_all_six_detection_measures_are_shown_each_with_a_plain_meaning(self):
        source = self.source()
        block = source[source.index('const METRICS = ['):source.index('function renderDetection')]
        for key in ('precision', 'recall', 'f1', 'roc_auc', 'pr_auc', 'fpr'):
            assert f'["{key}"' in block, key
        assert len(re.findall(r'\["\w+", "[^"]+", \d, "[^"]{20,}"\]', block)) == 6          # key, name, digits, meaning
        assert 'stat-help' in source and '95% interval' in source

    def test_the_page_keeps_the_model_apart_from_where_it_runs(self):
        html, source = self.html(), self.source()
        assert 'Risk Score' in html and 'Detection metrics' in html and 'Decision latency' in html
        assert 'This section is about the model, not about where it runs' in source
        assert 'detectionScope' in html

    def test_the_comparison_table_has_every_measure_and_marks_the_best(self):
        source = self.source()
        block = source[source.index('function renderBaseline'):source.index('// ---------- section 3')]
        for row in ('Decision latency, mean', 'Decision latency, median', 'Decision latency, 95th percentile', 'Processor seconds per 1,000 transactions',
                    'Processor utilization, average share of one core', 'Peak memory'):
            assert row in block, row
        assert 'bestFlags' in block and 'within 10%' in block

    def test_the_best_is_the_lowest_value_or_within_ten_per_cent_of_it(self):
        import shutil
        import subprocess
        node = shutil.which('node')
        if not node:
            pytest.skip('node is not installed')
        source = self.source()
        function = source[source.index('function bestFlags'):source.index('function renderBaseline')]
        script = function + 'console.log(JSON.stringify([bestFlags([5000, 23, 23]), bestFlags([1.47, 23.7, 23.6]), bestFlags([100, 109, 111]), bestFlags([7, null, undefined])]));'
        out = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=30).stdout.strip()
        assert json.loads(out) == [[False, True, True], [True, False, False], [True, True, False], [False, False, False]]

    def test_the_page_does_not_declare_a_universal_winner(self):
        source, html = self.source(), self.html()
        assert 'speed is not the only thing to weigh' in source
        assert 'What each design trades' in html and 'the best choice for a bank can differ' in html
        for claim in ('always best', 'universally', 'best architecture'):
            assert claim not in source and claim not in html

    def test_every_chart_has_a_title_axis_names_units_and_a_description(self):
        source, html = self.source(), self.html()
        ids = set(re.findall(r'(?:lineChart|barChart)\(document\.getElementById\("(\w+)"\)', source))
        assert ids == {'baselineChart', 'sweepChart', 'memoryChart', 'cpuChart', 'networkChart'}
        for chart in ids:
            assert re.search(r'<h[34] class="(?:subhead|chart-title)">[^<]+</h[34]>\s*(?:<div>\s*)?(?:<h4[^>]*>[^<]*</h4>\s*)?<div class="chart-wrap" id="' + chart + '"', html) or \
                re.search(r'<h4 class="chart-title">[^<]+</h4>\s*<div class="chart-wrap" id="' + chart + '"', html), chart
        # axis names, units and an accessible description are given wherever a chart is drawn
        assert source.count('xTitle:') >= 5 and source.count('yTitle:') >= 5 and source.count('label:') >= 5
        assert 'Peak memory (MB)' in source and 'Transactions arriving per second' in source and 'Round trip between application and database' in source

    def test_charts_use_the_same_colour_for_each_architecture_and_draw_for_the_phone(self):
        source = self.source()
        assert source.count('MODE_COLOR[') >= 5 and 'color: MODE_COLOR[mode]' in source
        for line in ('external_batch: "var(--yellow)"', 'in_database: "var(--blue)"', 'application: "var(--accent)"'):
            assert line in source
        assert 'function isNarrow' in source and 'redrawCharts' in source and '"resize"' in source
        css = (DASHBOARD / 'style.css').read_text(encoding='utf-8')
        assert '.results-table.stack' in css and 'attr(data-label)' in css

    def test_the_pipeline_is_a_numbered_workflow_that_says_what_the_benchmarks_cover(self):
        html = self.html()
        block = html[html.index('id="pipelinePanel"'):html.index('id="detectionPanel"')]
        assert len(re.findall(r'<li class="flow-step', block)) == 8
        moved = re.findall(r'<li class="flow-step moves">.*?<strong>(.*?)</strong>', block)
        assert moved == ['Thirty features are built', 'Four models score it', 'Weighted average']
        out = re.findall(r'<li class="flow-step out">.*?<strong>(.*?)</strong>', block)
        assert out == ['Three rule checks', 'Decision']
        assert 'XGBoost, LightGBM, a voting pair of those two, and an Isolation Forest' in block

    def test_the_weights_shown_are_the_weights_in_the_code(self):
        from advanced_ml_models import AdvancedFraudDetectionModel
        weights = AdvancedFraudDetectionModel.ENSEMBLE_WEIGHTS
        assert sorted(weights.values()) == [0.15, 0.15, 0.35, 0.35]
        assert 'Weights of 35%, 35%, 15% and 15%' in self.html()

    def test_the_limitations_are_listed_in_plain_view(self):
        html, source = self.html(), self.source()
        panel = html[html.index('id="notesPanel"'):html.index('id="learnPanel"')]
        assert '<details' not in panel and 'id="notesList"' in panel
        for text in ('European card transactions', 'that one machine', 'delaying relay', 'stand-ins', 'three evaluators',
                     'do not establish fraud rates or operational performance for any Ugandan bank', 'not a validated banking deployment'):
            assert text in source, text

    def test_the_page_links_back_and_the_architectures_are_named_the_same_everywhere(self):
        html, source = self.html(), self.source()
        assert html.count('href="index.html"') == 2
        index = (DASHBOARD / 'index.html').read_text(encoding='utf-8').lower()
        for name in ('external batch', 'in-database', 'application tier'):
            assert name in html.lower() and name in index, name
        for label in ('External batch', 'In-database', 'Application tier'):
            assert f'"{label}"' in source
