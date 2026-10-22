"""
Test set-up.

api_server.py builds the whole fraud system (trains the model, connects to
PostgreSQL) when it is imported. The tests do not need either, so a stand-in
FraudDetectionSystem is registered before the import. The tests then exercise
the real API code: authentication, validation, error handling and rate limits.
"""

import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_SECRET = 'test-secret-key-used-only-by-the-test-suite'
os.environ['SECRET_KEY'] = TEST_SECRET
for name in ('ADMIN_USERNAME', 'ADMIN_PASSWORD', 'ADMIN_PASSWORD_HASH', 'FLASK_DEBUG', 'CLIENT_IP_HEADER', 'RENDER'):
    os.environ.pop(name, None)


class StubDatabase:
    def get_customer_profile(self, customer_id):
        return {'customer_id': customer_id, 'name': 'Test Customer', 'recent_decisions': []}

    def get_latest_transactions(self, limit, decision=None):
        return []


class StubAnalytics:
    def get_fraud_statistics(self):
        return {'total_transactions': 0}

    def get_fraud_patterns(self):
        return []

    def get_roi_metrics(self):
        return {}

    def generate_executive_summary(self):
        return {}


class StubTransactionProcessor:
    def generate_sample_transactions(self, n=1):
        raise RuntimeError('not used in these tests')


class StubSystem:
    """Records the transactions it is asked to process"""

    def __init__(self):
        self.processed = []
        self.db_manager = StubDatabase()
        self.analytics = StubAnalytics()
        self.transaction_processor = StubTransactionProcessor()

    def setup_system(self):
        return []

    def process_transaction(self, txn, explain=False):
        self.processed.append(txn)
        result = {
            'transaction_id': txn['transaction_id'], 'customer_id': txn['customer_id'],
            'amount': txn['amount'], 'fraud_score': 0.1, 'is_fraud': False, 'decision': 'ALLOW',
        }
        return result


_stub_module = types.ModuleType('fraud_detection_system')
_stub_module.FraudDetectionSystem = StubSystem
sys.modules['fraud_detection_system'] = _stub_module

import api_server  # noqa: E402  (must come after the stand-in is registered)


@pytest.fixture
def make_api():
    """Build a fresh API (and so a fresh rate-limit counter) around a stub system"""
    def build(**kwargs):
        system = StubSystem()
        api = api_server.FraudDetectionAPI(system, **kwargs)
        return api, system
    return build


@pytest.fixture
def api_and_system(make_api):
    return make_api()


@pytest.fixture
def client(api_and_system):
    return api_and_system[0].app.test_client()


@pytest.fixture
def system(api_and_system):
    return api_and_system[1]


@pytest.fixture
def token(client):
    response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'})
    assert response.status_code == 200
    return response.get_json()['token']


@pytest.fixture
def auth(token):
    return {'Authorization': f'Bearer {token}'}
