"""Tests for the day and time of a transaction and for the reason shown with its decision.

The Time column used to show when the transaction was processed, so every row of a batch
showed the same minute while the Time of Day column showed the transaction's own time. Both
now come from the transaction's own time, and each decision carries a plain-sentence reason."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from test_explain import FixedProba, TXN, make_model, make_system, original_decision, real

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / 'admin-dashboard'
FLAGS = ['threshold_exceeded', 'velocity_anomaly', 'unusual_time']


def run_node(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    return subprocess.run([node, '-e', script], capture_output=True, text=True, encoding='utf-8', timeout=30).stdout.strip()


def time_functions():
    source = (DASHBOARD / 'script.js').read_text(encoding='utf-8')
    return source[source.index('function fmtTimeOfDay'):source.index('let decisionFilter')]


# ---------------------------------------------------------------- the reason

class TestReason:
    def test_a_blocked_transaction_says_which_rule_checks_fired(self):
        system = make_system(model=make_model(), recent=11)
        result = system.process_transaction(dict(TXN, amount=900.0, Time=2 * 3600))
        assert result['decision'] == 'BLOCK'
        reason = result['reason']
        assert reason.startswith('All three rule checks fired')
        assert 'UGX 3,600,000' in reason and 'average (UGX 400,000)' in reason
        assert '11 transactions in the hour before it' in reason
        assert '02:00 is an unusual time of day' in reason

    def test_block_by_score_and_one_rule_names_the_score_and_the_rule(self):
        system = make_system(recent=0)                        # the stand-in model scores 0.8 or so
        result = system.process_transaction(dict(TXN, amount=900.0, Time=12 * 3600))
        assert result['decision'] == 'BLOCK'
        assert 'above 50%' in result['reason'] and '1 rule check fired' in result['reason']
        assert 'over 5 times' in result['reason']

    def test_review_by_score_alone_and_monitor_say_no_rule_fired_where_that_is_true(self):
        review = make_system(model=make_model(xgboost=FixedProba(0.99), lightgbm=FixedProba(0.99), voting_ensemble=FixedProba(0.99)))
        result = review.process_transaction(dict(TXN))
        assert result['decision'] == 'REVIEW' and 'above 70%' in result['reason']
        monitor = make_system(model=make_model(xgboost=FixedProba(0.62), lightgbm=FixedProba(0.62), voting_ensemble=FixedProba(0.62)))
        result = monitor.process_transaction(dict(TXN))
        assert result['decision'] == 'MONITOR' and 'no rule check fired' in result['reason']

    def test_review_by_two_rules_names_both(self):
        quiet = make_model(xgboost=FixedProba(0.1), lightgbm=FixedProba(0.1), voting_ensemble=FixedProba(0.1))
        system = make_system(model=quiet, recent=11)
        result = system.process_transaction(dict(TXN, amount=900.0, Time=12 * 3600))
        assert result['decision'] == 'REVIEW'
        assert result['reason'].startswith('2 rule checks fired')
        assert 'over 5 times' in result['reason'] and '11 transactions' in result['reason']

    def test_an_allowed_transaction_says_why_nothing_happened(self):
        quiet = make_model(xgboost=FixedProba(0.05), lightgbm=FixedProba(0.05), voting_ensemble=FixedProba(0.05))
        result = make_system(model=quiet).process_transaction(dict(TXN))
        assert result['decision'] == 'ALLOW'
        assert 'no rule check fired' in result['reason']
        one = make_system(model=quiet).process_transaction(dict(TXN, amount=900.0))
        assert one['decision'] == 'ALLOW' and 'only 1 rule check fired' in one['reason'] and 'not enough to act' in one['reason']

    def test_every_case_gives_a_sentence_and_the_decision_is_unchanged(self):
        system = make_system()
        for fired in __import__('itertools').product([False, True], repeat=3):
            flags = dict(zip(FLAGS, fired))
            details = {'threshold_exceeded': {'amount': 900.0, 'customer_average': 100.0, 'limit': 500.0},
                       'velocity_anomaly': {'recent_count': 11, 'limit': 10},
                       'unusual_time': {'hour': 2}}
            for p in [0.0, 0.3, 0.5001, 0.6, 0.7001, 0.95]:
                decision, _ = system._decide(flags, p > 0.5, p)
                assert decision == original_decision(flags, p > 0.5, p)
                why = system._why(decision, flags, details, p, {'Time': 7200})
                assert isinstance(why, str) and why.endswith('.') and len(why) > 20

    def test_the_reason_is_stored_but_the_model_breakdown_is_not(self):
        system = make_system()
        result = system.process_transaction(dict(TXN), explain=True)
        stored = system.db_manager.logged[0]
        assert stored['reason'] == result['reason']
        assert 'explanation' not in stored
        assert 'components' not in json.dumps(stored)

    def test_the_reason_is_the_same_with_and_without_the_explanation(self):
        plain = make_system().process_transaction(dict(TXN))
        explained = make_system().process_transaction(dict(TXN), explain=True)
        assert plain['reason'] == explained['reason']

    def test_the_reason_is_saved_by_the_database_code_and_old_databases_get_the_column(self):
        source = (ROOT / 'database_module.py').read_text(encoding='utf-8')
        create = source.split('def create_tables')[1].split('def _insert_sample_customers')[0]
        assert 'reason TEXT' in create
        assert 'ALTER TABLE transactions ADD COLUMN IF NOT EXISTS reason TEXT' in create
        log = source.split('def log_transaction')[1].split('def log_fraud_alert')[0]
        assert 'status, reason)' in log and log.count('%s') == 10 and "transaction_data.get('reason')" in log


# ---------------------------------------------------------------- the date and time

class TestDateAndTime:
    def test_the_date_follows_the_dataset_time(self):
        script = time_functions() + 'console.log(JSON.stringify([fmtDateTime(0), fmtDateTime(64680), fmtDateTime(86399), fmtDateTime(86400 + 3 * 3600 + 21 * 60), fmtDateTime(172799), fmtDateTime(172800), fmtDateTime(null), fmtDateTime(undefined)]));'
        assert json.loads(run_node(script)) == ['1 Sep 2013, 00:00', '1 Sep 2013, 17:58', '1 Sep 2013, 23:59', '2 Sep 2013, 03:21',
                                                '2 Sep 2013, 23:59', '3 Sep 2013, 00:00', '–', '–']

    def test_the_date_and_time_always_ends_in_the_time_of_day(self):
        script = time_functions() + '''
          const bad = [];
          for (let s = 0; s < 259200; s += 997) { if (!fmtDateTime(s).endsWith(fmtTimeOfDay(s))) bad.push(s); }
          console.log(JSON.stringify(bad));'''
        assert json.loads(run_node(script)) == []

    def test_different_times_give_different_dates_and_times(self):
        script = time_functions() + 'console.log(JSON.stringify(new Set([12000, 61000, 90000, 150000, 172000].map(fmtDateTime)).size));'
        assert run_node(script) == '5'

    def test_both_columns_read_the_same_number_and_the_processing_time_stays_in_the_tooltip(self):
        script = (DASHBOARD / 'script.js').read_text(encoding='utf-8')
        row = script[script.index('const when ='):script.index('.join("")', script.index('const when ='))]
        assert 'fmtDateTime(tx.txn_time)' in row
        assert 'fmtTimeOfDay(tx.txn_time)' not in row        # one Date & Time column, no duplicate time column
        assert 'Processed' in row

    def test_the_table_has_six_clear_columns_and_says_a_row_can_be_selected(self):
        html = (DASHBOARD / 'index.html').read_text(encoding='utf-8')
        before = html.split('<tbody id="txTableBody">')[0]
        head = before[before.rindex('<table class="tx-table'):]          # the recent-transactions table
        labels = [re.sub(r'<span.*?</span>', '', h).strip() for h in re.findall(r'<th>(.*?)</th>', head)]
        assert labels == ['Date &amp; Time', 'Transaction ID', 'Customer', 'Amount', 'Risk Score', 'Decision']
        assert 'select a row for why' in head and 'Time of Day' not in head and 'Fraud Score' not in head
        assert 'colspan="6"' in html.split('txTableBody')[1].split('</tbody>')[0]


# ---------------------------------------------------------------- the clickable decision

class TestClickableDecision:
    def source(self):
        return (DASHBOARD / 'script.js').read_text(encoding='utf-8')

    def test_the_decision_is_a_button_with_a_hidden_reason_row_under_it(self):
        row = self.source()[self.source().index('const when ='):self.source().index('.join("")', self.source().index('const when ='))]
        assert '<button type="button" class="badge decision-btn' in row and 'aria-expanded' in row
        assert '<tr class="tx-detail"' in row and 'Why this transaction was' in row
        for part in ('Risk Score', 'System decision', 'Reason', 'Transaction</span>'):
            assert part in row

    def test_the_reason_is_escaped_and_missing_reasons_are_explained(self):
        row = self.source()[self.source().index('const when ='):self.source().index('.join("")', self.source().index('const when ='))]
        assert 'esc(tx.reason)' in row and 'Explanation unavailable' in row and 'No reason was stored' in row
        assert 'because' in row and 'Analyze it again' in row

    def test_clicking_opens_and_closes_the_row_and_survives_a_refresh(self):
        source = self.source()
        handler = source[source.index('function toggleDetails'):source.index('el.filterPills.addEventListener')]
        assert 'detail.hidden' in handler and 'aria-expanded' in handler and '"selected"' in handler
        assert 'openDetails.add' in handler and 'openDetails.delete' in handler
        assert 'tr.tx-row' in handler and 'customer-link' in handler
        assert 'openDetails.has(tx.transaction_id)' in source

    def test_every_decision_has_a_plain_word_for_the_heading(self):
        script = (DASHBOARD / 'script.js').read_text(encoding='utf-8')
        words = script[script.index('const DECISION_WORDS'):script.index('const openDetails')]
        for decision in ('BLOCK', 'REVIEW', 'MONITOR', 'ALLOW'):
            assert decision in words

    def test_the_styles_for_the_button_and_the_reason_box_exist(self):
        css = (DASHBOARD / 'style.css').read_text(encoding='utf-8')
        for selector in ('button.badge.decision-btn', '.tx-detail[hidden]', '.why-box', '.why-box.decision-BLOCK',
                         'tr.tx-row.selected', '.why-flow', '.tx-table.stacked'):
            assert selector in css


# ---------------------------------------------------------------- the velocity rule uses the transaction's own time

class TestVelocityByOwnTime:
    def test_a_single_analysis_asks_for_the_hour_before_the_transactions_own_time(self):
        calls = []

        class Recording(make_system().db_manager.__class__):
            def get_recent_transactions(self, customer_id, minutes, at_seconds=None):
                calls.append((minutes, at_seconds))
                return []

        system = make_system()
        system.db_manager = Recording()
        system.process_transaction(dict(TXN, Time=90000.0))
        system.process_transaction({k: v for k, v in TXN.items() if k != 'Time'})
        assert calls == [(60, 90000.0), (60, None)]               # with a time, by its own time; without, as before

    def test_the_database_counts_by_the_transactions_own_time(self):
        source = (ROOT / 'database_module.py').read_text(encoding='utf-8')
        recent = source.split('def get_recent_transactions')[1].split('def get_customer_transaction_times')[0]
        assert 'txn_time > %s AND txn_time <= %s' in recent and 'at_seconds - minutes * 60' in recent
        assert 'timestamp > %s' in recent                           # the wall-clock count is still there for a transaction with no time
        assert 'def get_customer_transaction_times' in source


# ---------------------------------------------------------------- Risk Score wording and thresholds

class TestRiskScoreWording:
    def test_scores_are_shown_out_of_100_without_changing_the_stored_value(self):
        source = (DASHBOARD / 'script.js').read_text(encoding='utf-8')
        function = source[source.index('function fmtScore'):source.index('// The cut-offs')]
        script = function + 'console.log(JSON.stringify([fmtScore(0.944), fmtScore(0.089), fmtScore(1), fmtScore(0), fmtScore(null), fmtScore(undefined)]));'
        assert json.loads(run_node(script)) == ['94.4/100', '8.9/100', '100.0/100', '0.0/100', '\u2013', '\u2013']

    def test_no_dashboard_page_calls_the_score_a_fraud_score(self):
        for name in ('index.html', 'script.js', 'explain.js', 'results.html'):
            text = (DASHBOARD / name).read_text(encoding='utf-8')
            assert 'Fraud Score' not in text and 'fraud score' not in text.lower(), name

    def test_the_score_is_never_called_a_probability(self):
        for name in ('index.html', 'script.js', 'explain.js'):
            text = (DASHBOARD / name).read_text(encoding='utf-8').lower()
            for denial in ('not a calibrated probability', 'not a probability', 'never a probability'):
                text = text.replace(denial, '')          # only to say it is not one
            assert 'probability' not in text, name

    def test_the_cutoffs_shown_are_the_ones_the_decision_logic_uses(self):
        script = (DASHBOARD / 'script.js').read_text(encoding='utf-8')
        assert 'const SCORE_THRESHOLDS = { fraud: 50, review: 70 }' in script
        system = make_system()
        none = dict.fromkeys(['threshold_exceeded', 'velocity_anomaly', 'unusual_time'], False)
        assert system._decide(none, False, 0.5)[0] == 'ALLOW' and system._decide(none, True, 0.5001)[0] == 'MONITOR'
        assert system._decide(none, True, 0.7)[0] == 'MONITOR' and system._decide(none, True, 0.7001)[0] == 'REVIEW'

    def test_the_analyze_result_and_explanation_show_score_then_decision(self):
        script = (DASHBOARD / 'script.js').read_text(encoding='utf-8')
        start = script.index('el.analyzeResult.innerHTML')
        analyze = script[start:script.index('el.analyzeResult.hidden = false;', start)]
        assert analyze.index('Risk Score') < analyze.index('System decision')
        explain = (DASHBOARD / 'explain.js').read_text(encoding='utf-8')
        assert explain.index('"Risk Score"') < explain.index('"System decision"')

    def test_amounts_carry_a_ugx_label_without_changing_the_figure(self):
        source = (DASHBOARD / 'script.js').read_text(encoding='utf-8')
        function = source[source.index('function fmtAmount'):source.index('// The stored score')]
        script = 'const window = {DEMO_UGX_PER_UNIT: 4000};' + function + 'console.log(JSON.stringify([fmtAmount(125), fmtAmount(250), fmtAmount(526), fmtAmount(1), fmtAmount(0.77), fmtAmount(null)]));'
        assert json.loads(run_node(script)) == ['UGX 500,000', 'UGX 1,000,000', 'UGX 2,104,000', 'UGX 4,000', 'UGX 3,080', '–']

    def test_the_dashboard_and_the_stored_reasons_use_the_same_rate(self):
        explain = (DASHBOARD / 'explain.js').read_text(encoding='utf-8')
        assert 'window.DEMO_UGX_PER_UNIT = 4000;' in explain
        assert real.DEMO_UGX_PER_UNIT == 4000
        assert 'at UGX 4,000 for each unit' in (DASHBOARD / 'index.html').read_text(encoding='utf-8')

    def test_the_rate_changes_only_the_writing_never_the_amount_or_the_decision(self):
        txn = dict(TXN, amount=900.0, Time=2 * 3600)
        result = make_system(recent=11).process_transaction(dict(txn))
        assert result['amount'] == 900.0 and result['decision'] == 'BLOCK'
        assert make_system(recent=11).process_transaction(dict(txn))['fraud_score'] == result['fraud_score']

    def test_the_page_says_the_ugx_label_is_for_the_demonstration(self):
        html = (DASHBOARD / 'index.html').read_text(encoding='utf-8')
        assert 'shown in UGX for the demonstration' in html and 'stored amounts' in html and 'decisions do not' in html


# ---------------------------------------------------------------- uploads keep each transaction with its own customer

class TestUploadCustomers:
    def source(self):
        source = (DASHBOARD / 'script.js').read_text(encoding='utf-8')
        return source[source.index('el.uploadForm.addEventListener'):source.index('// ---------- Start a new evaluation session')]

    def test_every_row_goes_to_its_own_customer_whatever_is_chosen(self):
        code = self.source()
        assert 'fixedCustomer' not in code
        assert 'const customerId = DEMO_CUSTOMERS[i % DEMO_CUSTOMERS.length];' in code

    def test_the_choice_only_filters_the_rows_listed_under_the_form(self):
        code = self.source()
        assert 'const onlyCustomer = el.uCustomer.value !== "ALL"' in code
        assert 'results.filter((r) => r.customer_id === onlyCustomer)' in code
        assert 'el.uploadTableBody.innerHTML = shown' in code
        assert 'were analyzed under their own customers and are in Recent Transactions' in code

    def test_the_selector_offers_all_customers_and_each_one_alone(self):
        html = (DASHBOARD / 'index.html').read_text(encoding='utf-8')
        block = html[html.index('<select id="uCustomer">'):html.index('</select>', html.index('<select id="uCustomer">'))]
        assert 'value="ALL" selected' in block and 'ROTATE' not in block
        assert len(re.findall(r'value="CUST0\d\d">List only CUST0\d\d', block)) == 10
