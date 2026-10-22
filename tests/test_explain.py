"""Tests for "how this score was made": the model breakdown, the rule and decision
explanation, the API wiring and the dashboard code that shows it.

The breakdown must never change a result, so these tests compare it with the
code that produces the score and with the original decision logic."""

import importlib.util
import itertools
import re
from pathlib import Path

import numpy as np
import pytest

from advanced_ml_models import AdvancedFraudDetectionModel

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / 'admin-dashboard'


def load_real_system_module():
    """The real fraud_detection_system (conftest registers a stand-in under that name)"""
    spec = importlib.util.spec_from_file_location('real_fraud_detection_system', ROOT / 'fraud_detection_system.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


real = load_real_system_module()


# ---------------------------------------------------------------- stand-ins

class FixedProba:
    """Stands in for a model that gives every row the same fraud probability"""

    def __init__(self, p):
        self.p = p

    def predict_proba(self, X):
        return np.column_stack([1 - np.full(len(X), self.p), np.full(len(X), self.p)])


class FixedAnomaly:
    def __init__(self, s):
        self.s = s

    def score_samples(self, X):
        return np.full(len(X), self.s)


class IdentityScaler:
    def transform(self, X):
        return X


def make_model(**overrides):
    model = object.__new__(AdvancedFraudDetectionModel)
    model.scaler = IdentityScaler()
    model.models = {
        'xgboost': FixedProba(0.9),
        'lightgbm': FixedProba(0.7),
        'isolation_forest': FixedAnomaly(-0.5),
        'voting_ensemble': FixedProba(0.8),
        'one_class_svm': object(),
    }
    model.models.update(overrides)
    model.is_trained = True
    return model


# ---------------------------------------------------------------- the model

class TestModelBreakdown:
    def test_final_score_is_exactly_the_score_the_model_gives(self):
        model = make_model()
        row = np.zeros(30)
        explained = model.explain_score(row)
        assert explained['final_score'] == model.score_batch(row.reshape(1, -1))[0]
        assert explained['final_score'] == model.predict_fraud_advanced(row)

    def test_each_model_contributes_its_score_times_its_weight(self):
        explained = make_model().explain_score(np.zeros(30))
        by_name = {c['model']: c for c in explained['components']}
        assert set(by_name) == {'xgb', 'lgb', 'iso', 'voting'}
        assert by_name['xgb']['score'] == pytest.approx(0.9)
        assert by_name['xgb']['weight'] == pytest.approx(0.35)
        assert by_name['xgb']['contribution'] == pytest.approx(0.9 * 0.35)
        assert by_name['iso']['score'] == pytest.approx(1 / (1 + np.exp(-0.5)))

    def test_contributions_add_up_to_the_final_score(self):
        explained = make_model().explain_score(np.zeros(30))
        assert sum(c['contribution'] for c in explained['components']) == pytest.approx(explained['final_score'])
        assert sum(c['weight'] for c in explained['components']) == pytest.approx(1.0)

    def test_the_one_class_svm_is_not_part_of_the_breakdown(self):
        names = {c['model'] for c in make_model().explain_score(np.zeros(30))['components']}
        assert 'one_class_svm' not in names and 'svm' not in names

    def test_a_missing_model_is_left_out_and_the_weights_are_rescaled(self):
        model = make_model()
        del model.models['isolation_forest']
        explained = model.explain_score(np.zeros(30))
        assert {c['model'] for c in explained['components']} == {'xgb', 'lgb', 'voting'}
        assert explained['final_score'] == model.score_batch(np.zeros((1, 30)))[0]

    def test_an_untrained_model_gives_no_explanation(self):
        model = make_model()
        model.is_trained = False
        assert model.explain_score(np.zeros(30)) is None

    def test_scores_from_a_real_model_are_unchanged(self):
        """The saved benchmark model, when present, scores identically through both paths"""
        path = ROOT / 'benchmark_model.pkl'
        if not path.exists():
            pytest.skip('benchmark_model.pkl is not present')
        from near_data_scoring import load_model
        from feature_engineering import FEATURE_NAMES
        model = load_model(str(path))
        rng = np.random.default_rng(1)
        X = rng.normal(size=(20, len(FEATURE_NAMES)))
        X[:, 0] = rng.random(20)
        scores = model.score_batch(X)
        for i in range(len(X)):
            assert model.explain_score(X[i])['final_score'] == scores[i]


# ---------------------------------------------------------------- rules and decision

def original_decision(sql_flags, ml_fraud, fraud_probability):
    """The decision logic as it was before the reason was added"""
    count = sum(1 for v in sql_flags.values() if v)
    if count >= 3 or (ml_fraud and count >= 1):
        return 'BLOCK'
    elif count >= 2 or fraud_probability > 0.7:
        return 'REVIEW'
    elif ml_fraud or fraud_probability > 0.5:
        return 'MONITOR'
    return 'ALLOW'


class StubDb:
    def __init__(self, recent=0):
        self.recent = recent
        self.logged = []

    def get_customer_profile(self, customer_id):
        return {'avg_transaction': 100.0, 'unusual_hours_frequency': 0.05}

    def get_recent_transactions(self, customer_id, minutes):
        return [object()] * self.recent

    def log_transaction(self, result):
        self.logged.append(dict(result))

    def log_fraud_alert(self, result):
        pass


class StubProcessor:
    def extract_features(self, transaction, profile):
        return np.zeros(30)


def make_system(model=None, recent=0):
    system = object.__new__(real.FraudDetectionSystem)
    system.db_manager = StubDb(recent)
    system.transaction_processor = StubProcessor()
    system.ml_model = model or make_model()
    return system


TXN = {'transaction_id': 'T1', 'customer_id': 'CUST001', 'amount': 50.0, 'Time': 12 * 3600}


class TestDecision:
    def test_decision_matches_the_original_logic_for_every_case(self):
        system = make_system()
        names = ['threshold_exceeded', 'velocity_anomaly', 'unusual_time']
        probabilities = [0.0, 0.3, 0.5, 0.5001, 0.6, 0.7, 0.7001, 0.95, 1.0]
        for fired in itertools.product([False, True], repeat=3):
            flags = dict(zip(names, fired))
            for p in probabilities:
                ml_fraud = p > 0.5
                decision, reason = system._decide(flags, ml_fraud, p)
                assert decision == original_decision(flags, ml_fraud, p), (flags, p)
                assert system._combine_detections(flags, ml_fraud, p) == decision
                assert reason and isinstance(reason, str)

    def test_each_reason_names_its_own_condition(self):
        system = make_system()
        none = dict.fromkeys(['threshold_exceeded', 'velocity_anomaly', 'unusual_time'], False)
        one = dict(none, threshold_exceeded=True)
        two = dict(one, velocity_anomaly=True)
        three = dict(two, unusual_time=True)
        assert 'All three' in system._decide(three, False, 0.1)[1]
        assert 'at least one rule' in system._decide(one, True, 0.9)[1]
        assert 'Two rule checks' in system._decide(two, False, 0.1)[1]
        assert '0.7' in system._decide(none, True, 0.8)[1]
        assert 'no rule check fired' in system._decide(none, True, 0.6)[1]
        assert 'at or below 0.5' in system._decide(none, False, 0.2)[1]


class TestRules:
    def test_flags_are_unchanged_and_details_report_the_figures_compared(self):
        system = make_system(recent=11)
        txn = dict(TXN, amount=900.0, Time=2 * 3600)
        flags, details = system._evaluate_rules(txn, system.db_manager.get_customer_profile('CUST001'))
        assert flags == {'threshold_exceeded': True, 'velocity_anomaly': True, 'unusual_time': True}
        assert flags == system._perform_sql_filtering(txn, system.db_manager.get_customer_profile('CUST001'))
        assert details['threshold_exceeded'] == {'amount': 900.0, 'customer_average': 100.0, 'limit': 500.0}
        assert details['velocity_anomaly'] == {'recent_count': 11, 'limit': 10}
        assert details['unusual_time']['hour'] == 2 and details['unusual_time']['outside_hours'] is True

    def test_quiet_transaction_fires_nothing(self):
        system = make_system(recent=0)
        flags, details = system._evaluate_rules(TXN, system.db_manager.get_customer_profile('CUST001'))
        assert not any(flags.values())
        assert details['unusual_time']['outside_hours'] is False


class TestProcessTransaction:
    def test_without_explain_the_result_is_as_before(self):
        result = make_system().process_transaction(dict(TXN))
        assert 'explanation' not in result

    def test_explain_adds_the_explanation_and_changes_nothing_else(self):
        plain = make_system().process_transaction(dict(TXN))
        explained = make_system().process_transaction(dict(TXN), explain=True)
        for key in ('fraud_score', 'is_fraud', 'decision', 'sql_flags', 'confidence', 'amount'):
            assert explained[key] == plain[key], key
        info = explained['explanation']
        assert info['models']['final_score'] == explained['fraud_score']
        assert set(info['rules']) == {'threshold_exceeded', 'velocity_anomaly', 'unusual_time'}
        assert info['decision_reason']

    def test_the_explanation_is_not_stored_in_the_database(self):
        system = make_system()
        system.process_transaction(dict(TXN), explain=True)
        assert system.db_manager.logged and 'explanation' not in system.db_manager.logged[0]

    def test_explanation_is_json_serialisable(self):
        import json
        json.dumps(make_system().process_transaction(dict(TXN), explain=True))


# ---------------------------------------------------------------- the API

class TestApi:
    def test_single_analysis_asks_for_the_explanation_and_batch_does_not(self, client, auth, system):
        calls = []
        original = system.process_transaction

        def record(txn, explain=False, batch=None):
            calls.append(explain)
            return original(txn, explain, batch)

        system.process_transaction = record
        txn = {'transaction_id': 'T1', 'customer_id': 'CUST001', 'amount': 10}
        assert client.post('/api/transactions/analyze', json=txn, headers=auth).status_code == 200
        assert client.post('/api/transactions/batch-analyze', json={'transactions': [txn]}, headers=auth).status_code == 200
        assert calls == [True, False]


# ---------------------------------------------------------------- the dashboard code

class TestPage:
    def test_the_explanation_code_never_assigns_markup(self):
        source = (DASHBOARD / 'explain.js').read_text(encoding='utf-8')
        for unsafe in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval('):
            assert unsafe not in source, unsafe

    def test_the_dashboard_loads_the_explanation_code_before_the_script_that_uses_it(self):
        html = (DASHBOARD / 'index.html').read_text(encoding='utf-8')
        assert html.index('explain.js') < html.index('script.js')

    def test_the_elements_the_script_fills_exist(self):
        html = (DASHBOARD / 'index.html').read_text(encoding='utf-8')
        for element_id in ('analyzeExplainBox', 'analyzeExplain'):
            assert f'id="{element_id}"' in html
            assert f'getElementById("{element_id}")' in (DASHBOARD / 'script.js').read_text(encoding='utf-8')

    def test_the_pipeline_panel_states_what_the_study_moves(self):
        html = (DASHBOARD / 'results.html').read_text(encoding='utf-8')
        assert 'id="pipelinePanel"' in html
        assert len(re.findall(r'class="flow-step moves"', html)) == 3
        for architecture in ('External batch', 'In-database', 'Application tier'):
            assert architecture in html
