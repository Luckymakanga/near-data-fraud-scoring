"""The Customer Risk Profile on the dashboard: no names, the overall risk shown apart from the
decisions on single transactions, and counts that come only from the decisions the API returns.

This is presentation only: the classification is the one stored on the customer's record, and
nothing here changes what the API sends."""

import json
import re
from pathlib import Path

from test_time_and_reason import DASHBOARD, ROOT, run_node


def script_text():
    return (DASHBOARD / 'script.js').read_text(encoding='utf-8')


def helpers():
    source = script_text()
    return source[source.index('const CUSTOMER_RISK'):source.index('async function lookupCustomer')]


def render_function():
    source = script_text()
    return source[source.index('async function lookupCustomer'):source.index('el.lookupForm.addEventListener')]


class TestRiskLabels:
    def test_the_three_stored_classifications_are_worded_low_medium_and_high(self):
        script = helpers() + '''
          const out = ['LOW_RISK', 'NORMAL', 'HIGH_ACTIVITY'].map((s) => customerRisk(s));
          console.log(JSON.stringify(out));'''
        assert json.loads(run_node(script)) == [
            {'word': 'LOW RISK', 'level': 'LOW', 'stored': 'LOW_RISK'},
            {'word': 'MEDIUM RISK', 'level': 'MEDIUM', 'stored': 'NORMAL'},
            {'word': 'HIGH RISK', 'level': 'HIGH', 'stored': 'HIGH_ACTIVITY'},
        ]

    def test_a_missing_or_unknown_classification_is_not_replaced_by_a_guess(self):
        script = helpers() + 'console.log(JSON.stringify([customerRisk(undefined), customerRisk(null), customerRisk("UNDER_WATCH")]));'
        assert json.loads(run_node(script)) == [
            {'word': 'NOT CLASSIFIED', 'level': 'NONE', 'stored': None},
            {'word': 'NOT CLASSIFIED', 'level': 'NONE', 'stored': None},
            {'word': 'UNDER WATCH', 'level': 'NONE', 'stored': 'UNDER_WATCH'},
        ]

    def test_every_classification_the_system_stores_has_a_label(self):
        seed = (ROOT / 'database_module.py').read_text(encoding='utf-8')
        stored = set(re.findall(r"\('CUST\d+',.*?, '([A-Z_]+)'\)", seed))
        assert stored == {'LOW_RISK', 'NORMAL', 'HIGH_ACTIVITY'}
        script = helpers() + 'console.log(JSON.stringify(%s.map((s) => customerRisk(s).level)));' % json.dumps(sorted(stored))
        assert 'NONE' not in json.loads(run_node(script))

    def test_the_stored_label_is_shown_beside_the_new_wording(self):
        assert 'System classification: ${esc(risk.stored)}' in render_function()

    def test_the_old_default_of_normal_is_gone(self):
        assert 'profile.risk_level || "NORMAL"' not in script_text()


class TestDecisionCounts:
    def test_counts_come_only_from_the_decisions_given(self):
        script = helpers() + '''
          console.log(JSON.stringify([
            countDecisions(["ALLOW","ALLOW","BLOCK","REVIEW","ALLOW","MONITOR","ALLOW","ALLOW","ALLOW","ALLOW"]),
            countDecisions([]), countDecisions(undefined), countDecisions(["ALLOW","SOMETHING_ELSE"]),
          ]));'''
        assert json.loads(run_node(script)) == [
            {'ALLOW': 7, 'REVIEW': 1, 'BLOCK': 1, 'MONITOR': 1},
            {'ALLOW': 0, 'REVIEW': 0, 'BLOCK': 0, 'MONITOR': 0},
            {'ALLOW': 0, 'REVIEW': 0, 'BLOCK': 0, 'MONITOR': 0},
            {'ALLOW': 1, 'REVIEW': 0, 'BLOCK': 0, 'MONITOR': 0},
        ]

    def test_the_summary_says_how_many_transactions_it_covers(self):
        code = render_function()
        assert 'latest ${recent.length} analyzed transaction' in code
        assert 'No transactions have been analyzed for this customer yet.' in code


class TestLayout:
    def test_the_customer_name_is_never_shown(self):
        code = render_function()
        assert 'esc(profile.name)' not in code
        assert code.count('profile.name') == 1                  # only the check that a record exists
        assert 'Customer ID: ${esc(profile.customer_id)}' in code

    def test_the_category_and_the_indicators_are_kept(self):
        code = render_function()
        assert 'esc(profile.account_type' in code
        for label in ('Average transaction amount', 'Last transaction location', 'Unusual-hours transactions'):
            assert label in code
        assert 'fmtAmount(profile.avg_transaction)' in code and 'fmtFreq(profile.unusual_hours_frequency)' in code

    def test_overall_risk_and_transaction_decisions_are_separate_labelled_sections(self):
        code = render_function()
        assert code.index('Overall Customer Risk') < code.index('Risk Indicators') < code.index('Recent Transaction Decisions')
        assert 'not the result of any single transaction' in code
        assert 'LOW RISK overall and still have a transaction blocked' in code

    def test_the_styles_exist_for_every_risk_level_and_the_sections(self):
        css = (DASHBOARD / 'style.css').read_text(encoding='utf-8')
        for selector in ('.risk-badge.risk-LOW', '.risk-badge.risk-MEDIUM', '.risk-badge.risk-HIGH', '.risk-badge.risk-NONE',
                         '.profile-section', '.profile-heading', '.count-list'):
            assert selector in css
