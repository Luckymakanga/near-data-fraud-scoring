"""Tests for the security fixes: validation, login, signing key, error handling"""

import logging
import subprocess
import re
import shutil
from pathlib import Path

import jwt
import pytest
from werkzeug.security import generate_password_hash

from conftest import TEST_SECRET, StubSystem
import api_server
from validation import validate_transaction

GOOD = {'transaction_id': 'TXN4F2A9C1B', 'customer_id': 'CUST001', 'amount': 12.5}
XSS_ID = '<img src=x onerror=alert(1)>'


# ---------------------------------------------------------------- validation

class TestValidation:
    def test_accepts_the_ids_the_system_generates(self):
        for transaction_id, customer_id in [('TXN4F2A9C1B', 'CUST001'), ('LIVE8D3E21AA', 'CUST010'),
                                            ('TXNMGK3Q2P7', 'CUST005'), ('a-b_c-1', 'x')]:
            assert validate_transaction({'transaction_id': transaction_id, 'customer_id': customer_id, 'amount': 1}) is None

    @pytest.mark.parametrize('bad_id', [
        XSS_ID, '"><script>alert(1)</script>', "x' OR '1'='1", 'has space', 'semi;colon',
        'a' * 65, '', 'ünïcode', '../../etc/passwd', 123, None, ['CUST001'],
    ])
    def test_rejects_unsafe_ids(self, bad_id):
        assert validate_transaction({**GOOD, 'transaction_id': bad_id}) is not None
        assert validate_transaction({**GOOD, 'customer_id': bad_id}) is not None

    @pytest.mark.parametrize('bad_amount', [True, False, '12.5', None, float('nan'), float('inf'), -1, 1e13, [1], {}])
    def test_rejects_bad_amounts(self, bad_amount):
        assert validate_transaction({**GOOD, 'amount': bad_amount}) is not None

    @pytest.mark.parametrize('amount', [0, 0.0, 1, 12.5, 999999999999])
    def test_accepts_real_amounts_including_zero(self, amount):
        assert validate_transaction({**GOOD, 'amount': amount}) is None

    def test_reports_missing_fields_and_non_objects(self):
        assert 'amount' in validate_transaction({'transaction_id': 'T1', 'customer_id': 'C1'})
        for not_an_object in (None, 'text', 5, [GOOD]):
            assert validate_transaction(not_an_object) is not None


# ---------------------------------------------------------------- login

class TestLogin:
    def test_demo_credentials_still_work_when_nothing_is_configured(self, client):
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'}).status_code == 200

    def test_wrong_credentials_are_rejected(self, client):
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'nope'}).status_code == 401
        assert client.post('/api/auth/login', json={'username': 'root', 'password': 'admin'}).status_code == 401

    @pytest.mark.parametrize('payload', [None, [], 'text', {'username': 'admin'}, {'username': 1, 'password': 2}])
    def test_bad_bodies_get_a_400_not_a_crash(self, client, payload):
        response = client.post('/api/auth/login', json=payload) if payload is not None else client.post('/api/auth/login')
        assert response.status_code == 400

    def test_a_warning_is_logged_when_the_demo_password_is_in_use(self, make_api, caplog):
        with caplog.at_level(logging.WARNING):
            make_api()
        assert 'public demo password' in caplog.text

    def test_password_from_the_environment_replaces_the_demo_one(self, make_api, monkeypatch):
        monkeypatch.setenv('ADMIN_USERNAME', 'bursar')
        monkeypatch.setenv('ADMIN_PASSWORD', 'a-long-unguessable-passphrase')
        client = make_api()[0].app.test_client()
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'}).status_code == 401
        assert client.post('/api/auth/login', json={'username': 'bursar', 'password': 'a-long-unguessable-passphrase'}).status_code == 200

    def test_password_hash_is_supported_and_preferred(self, make_api, monkeypatch):
        monkeypatch.setenv('ADMIN_PASSWORD_HASH', generate_password_hash('hashed-secret'))
        monkeypatch.setenv('ADMIN_PASSWORD', 'ignored-when-a-hash-is-set')
        client = make_api()[0].app.test_client()
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'hashed-secret'}).status_code == 200
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'ignored-when-a-hash-is-set'}).status_code == 401
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'admin'}).status_code == 401

    def test_login_attempts_are_rate_limited(self, client):
        codes = [client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'}).status_code for _ in range(12)]
        assert codes[:10] == [401] * 10
        assert 429 in codes[10:]


# ---------------------------------------------------------------- signing key

class TestSigningKey:
    def test_refuses_to_start_without_a_key_outside_debug_mode(self, make_api, monkeypatch):
        monkeypatch.delenv('SECRET_KEY')
        with pytest.raises(RuntimeError, match='SECRET_KEY is not set'):
            make_api(debug=False)

    def test_debug_mode_uses_a_development_key_and_warns(self, make_api, monkeypatch, caplog):
        monkeypatch.delenv('SECRET_KEY')
        with caplog.at_level(logging.WARNING):
            api, _ = make_api(debug=True)
        assert 'development-only key' in caplog.text
        assert api.app.config['SECRET_KEY'] != TEST_SECRET

    def test_tokens_signed_with_the_old_built_in_key_are_rejected(self, client):
        forged = jwt.encode({'username': 'admin'}, 'uganda-fraud-detection-secret-key', algorithm='HS256')
        response = client.post('/api/transactions/analyze', json=GOOD, headers={'Authorization': f'Bearer {forged}'})
        assert response.status_code == 401

    def test_a_token_that_asks_for_no_signature_is_rejected(self, client):
        unsigned = jwt.encode({'username': 'admin'}, key=None, algorithm='none')
        response = client.post('/api/transactions/analyze', json=GOOD, headers={'Authorization': f'Bearer {unsigned}'})
        assert response.status_code == 401


# ---------------------------------------------------------------- protected routes and validation

class TestRoutes:
    @pytest.mark.parametrize('method,path', [
        ('post', '/api/transactions/analyze'), ('post', '/api/transactions/batch-analyze'),
        ('get', '/api/transactions/recent'), ('get', '/api/transactions/sample'),
        ('get', '/api/statistics/fraud'), ('get', '/api/statistics/patterns'),
        ('get', '/api/customers/CUST001/risk-profile'), ('get', '/api/metrics/roi'),
        ('get', '/api/reports/executive-summary'),
    ])
    def test_every_protected_route_needs_a_token(self, client, method, path):
        assert getattr(client, method)(path).status_code == 401

    def test_health_and_login_are_open(self, client):
        assert client.get('/api/health').status_code == 200

    def test_a_valid_transaction_is_processed(self, client, auth, system):
        response = client.post('/api/transactions/analyze', json=GOOD, headers=auth)
        assert response.status_code == 200
        assert system.processed == [GOOD]

    def test_a_script_in_an_id_is_refused_and_never_reaches_the_system(self, client, auth, system):
        for field in ('transaction_id', 'customer_id'):
            response = client.post('/api/transactions/analyze', json={**GOOD, field: XSS_ID}, headers=auth)
            assert response.status_code == 400
            assert field in response.get_json()['error']
        assert system.processed == []

    def test_a_missing_or_non_json_body_is_a_400(self, client, auth):
        assert client.post('/api/transactions/analyze', headers=auth).status_code == 400
        assert client.post('/api/transactions/analyze', json=[GOOD], headers=auth).status_code == 400

    def test_batch_skips_bad_rows_and_reports_why(self, client, auth, system):
        batch = [GOOD, {**GOOD, 'transaction_id': XSS_ID}, {**GOOD, 'transaction_id': 'T2', 'amount': 'lots'}, {**GOOD, 'transaction_id': 'T3'}]
        body = client.post('/api/transactions/batch-analyze', json={'transactions': batch}, headers=auth).get_json()
        assert body['summary'] == {'total': 2, 'fraud_count': 0, 'skipped': 2}
        assert [e['index'] for e in body['errors']] == [1, 2]
        assert [t['transaction_id'] for t in system.processed] == ['TXN4F2A9C1B', 'T3']

    def test_batch_rejects_wrong_shapes(self, client, auth):
        assert client.post('/api/transactions/batch-analyze', json={'transactions': 'x'}, headers=auth).status_code == 400
        assert client.post('/api/transactions/batch-analyze', json={}, headers=auth).status_code == 400
        assert client.post('/api/transactions/batch-analyze', json={'transactions': [GOOD] * 501}, headers=auth).status_code == 400

    def test_customer_id_in_the_url_is_validated(self, client, auth):
        assert client.get('/api/customers/CUST001/risk-profile', headers=auth).status_code == 200
        assert client.get('/api/customers/%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E/risk-profile', headers=auth).status_code == 400
        assert client.get('/api/customers/' + 'a' * 65 + '/risk-profile', headers=auth).status_code == 400
        # an encoded slash becomes a path separator, so the request never matches the route
        assert client.get('/api/customers/%3Cscript%3E%3C%2Fscript%3E/risk-profile', headers=auth).status_code == 404

    def test_existing_filter_validation_is_unchanged(self, client, auth):
        assert client.get('/api/transactions/recent?decision=BOGUS', headers=auth).status_code == 400
        assert client.get('/api/transactions/recent?decision=BLOCK&limit=5', headers=auth).status_code == 200


# ---------------------------------------------------------------- error handling

class TestErrors:
    def test_server_errors_do_not_leak_details_but_are_logged_with_a_reference(self, client, auth, system, caplog):
        secret_detail = 'connection to server at "10.1.2.3" failed: password authentication failed for user "fraud_app"'

        def explode(_txn):
            raise RuntimeError(secret_detail)
        system.process_transaction = explode

        with caplog.at_level(logging.ERROR):
            response = client.post('/api/transactions/analyze', json=GOOD, headers=auth)

        body = response.get_json()
        assert response.status_code == 500
        assert body['error'] == 'Internal server error'
        assert re.fullmatch(r'[0-9a-f]{8}', body['error_id'])
        assert secret_detail not in response.get_data(as_text=True)
        assert secret_detail in caplog.text
        assert body['error_id'] in caplog.text

    @pytest.mark.parametrize('path', [
        '/api/statistics/fraud', '/api/statistics/patterns', '/api/metrics/roi', '/api/reports/executive-summary',
    ])
    def test_every_handler_hides_exception_text(self, client, auth, system, path):
        def explode(*_args, **_kwargs):
            raise RuntimeError('SECRET-INTERNAL-DETAIL')
        for name in ('get_fraud_statistics', 'get_fraud_patterns', 'get_roi_metrics', 'generate_executive_summary'):
            setattr(system.analytics, name, explode)
        response = client.get(path, headers=auth)
        assert response.status_code == 500
        assert 'SECRET-INTERNAL-DETAIL' not in response.get_data(as_text=True)

    def test_no_handler_in_the_source_still_returns_raw_exception_text(self):
        source = Path(api_server.__file__).read_text(encoding='utf-8')
        assert "jsonify({'error': str(e)})" not in source


# ---------------------------------------------------------------- dashboard escaping

@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is not installed')
class TestDashboardEscaping:
    SCRIPT = Path(__file__).resolve().parent.parent / 'admin-dashboard' / 'script.js'

    def run_esc(self, value_js):
        source = self.SCRIPT.read_text(encoding='utf-8')
        match = re.search(r'function esc\(value\) \{.*?\n\}\n', source, re.S)
        assert match, 'esc() not found in script.js'
        program = match.group(0) + f'\nconsole.log(JSON.stringify(esc({value_js})));'
        out = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
        import json
        return json.loads(out.stdout)

    def test_markup_is_neutralised(self):
        escaped = self.run_esc('"<img src=x onerror=alert(1)>"')
        assert '<' not in escaped and '>' not in escaped
        assert escaped == '&lt;img src=x onerror=alert(1)&gt;'

    def test_attribute_breakout_is_neutralised(self):
        escaped = self.run_esc('`" onmouseover="alert(1)` + "\' autofocus=\'"')
        assert '"' not in escaped and "'" not in escaped

    def test_ordinary_values_survive(self):
        assert self.run_esc('"CUST001"') == 'CUST001'
        assert self.run_esc('42') == '42'
        assert self.run_esc('null') == ''
        assert self.run_esc('undefined') == ''

    def test_no_api_field_is_interpolated_into_html_without_esc(self):
        # Fields that hold text an API caller can influence. Counts and other numbers
        # computed by the server cannot carry markup, so they are not checked here.
        text_fields = r'(?:transaction_id|customer_id|decision|name|account_type|last_location|risk_level|pattern)'
        source = self.SCRIPT.read_text(encoding='utf-8')
        expressions = re.findall(r'\$\{([^}]*\b' + text_fields + r'\b[^}]*)\}', source)
        assert expressions, 'expected to find template expressions using these fields'

        # `${decision}` is fine only if every definition of that variable is escaped
        definitions = re.findall(r'const decision = (.*?);', source)
        assert definitions and all('esc(' in d for d in definitions), definitions

        unescaped = [expr for expr in expressions if 'esc(' not in expr and expr.strip() != 'decision']
        assert unescaped == [], unescaped
