"""Roles and the lockout: who may do what, what a token's role can and cannot do, and the lockout after failed sign-ins.

There are three roles. An admin can do everything, including deleting the stored data. An analyst can view, analyze and
upload but cannot delete. A viewer can only read, which is the account for a public demonstration. The analyst and the
viewer exist only when their own environment variables are set."""

import logging
from datetime import datetime, timedelta

import jwt
import pytest
from werkzeug.security import generate_password_hash

from conftest import TEST_SECRET

ANALYST = ('analyst1', 'analyst-passphrase-1')
VIEWER = ('demo-viewer', 'viewer-passphrase-1')
ADMIN = ('admin', 'admin')

TXN = {'transaction_id': 'T1', 'customer_id': 'CUST001', 'amount': 10}
READS = [
    ('get', '/api/transactions/recent', None), ('get', '/api/transactions/sample', None), ('get', '/api/statistics/fraud', None),
    ('get', '/api/statistics/patterns', None), ('get', '/api/customers/CUST001/risk-profile', None), ('get', '/api/metrics/roi', None),
    ('get', '/api/reports/executive-summary', None), ('get', '/api/research/results', None),
]
WRITES = [('post', '/api/transactions/analyze', TXN), ('post', '/api/transactions/batch-analyze', {'transactions': [TXN]})]
DELETES = [('post', '/api/admin/reset-demo-data', {'confirm': 'RESET'})]


@pytest.fixture
def accounts(make_api, monkeypatch):
    monkeypatch.setenv('ANALYST_USERNAME', ANALYST[0])
    monkeypatch.setenv('ANALYST_PASSWORD', ANALYST[1])
    monkeypatch.setenv('VIEWER_USERNAME', VIEWER[0])
    monkeypatch.setenv('VIEWER_PASSWORD', VIEWER[1])
    api, system = make_api()
    return api, system, api.app.test_client()


def sign_in(client, who):
    response = client.post('/api/auth/login', json={'username': who[0], 'password': who[1]})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def headers(client, who):
    return {'Authorization': f"Bearer {sign_in(client, who)['token']}"}


def call(client, method, path, body, head):
    return getattr(client, method)(path, json=body, headers=head) if body is not None else getattr(client, method)(path, headers=head)


def allowed(client, request, head):
    status = call(client, *request, head).status_code
    assert status != 401, request
    return status != 403


class TestSigningInGivesARole:
    def test_each_account_signs_in_with_its_own_role(self, accounts):
        client = accounts[2]
        assert [sign_in(client, who)['role'] for who in (ADMIN, ANALYST, VIEWER)] == ['admin', 'analyst', 'viewer']

    def test_the_role_is_in_the_signed_token(self, accounts):
        client = accounts[2]
        for who, role in ((ADMIN, 'admin'), (ANALYST, 'analyst'), (VIEWER, 'viewer')):
            claims = jwt.decode(sign_in(client, who)['token'], TEST_SECRET, algorithms=['HS256'])
            assert claims['role'] == role and claims['username'] == who[0]

    def test_without_their_variables_the_analyst_and_viewer_do_not_exist(self, client):
        for who in (ANALYST, VIEWER):
            assert client.post('/api/auth/login', json={'username': who[0], 'password': who[1]}).status_code == 401
        assert sign_in(client, ADMIN)['role'] == 'admin'

    def test_an_account_needs_both_a_username_and_a_password(self, make_api, monkeypatch, caplog):
        monkeypatch.setenv('VIEWER_USERNAME', 'only-a-name')
        with caplog.at_level(logging.WARNING):
            client = make_api()[0].app.test_client()
        assert 'viewer account is not enabled' in caplog.text
        assert client.post('/api/auth/login', json={'username': 'only-a-name', 'password': ''}).status_code == 401

    def test_a_username_cannot_be_used_by_two_roles(self, make_api, monkeypatch, caplog):
        monkeypatch.setenv('ANALYST_USERNAME', 'admin')
        monkeypatch.setenv('ANALYST_PASSWORD', 'a-different-passphrase')
        with caplog.at_level(logging.WARNING):
            client = make_api()[0].app.test_client()
        assert 'already used by another role' in caplog.text
        assert sign_in(client, ADMIN)['role'] == 'admin'
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'a-different-passphrase'}).status_code == 401

    def test_a_password_hash_works_for_the_viewer(self, make_api, monkeypatch):
        monkeypatch.setenv('VIEWER_USERNAME', 'guest')
        monkeypatch.setenv('VIEWER_PASSWORD_HASH', generate_password_hash('hashed-viewer-secret'))
        client = make_api()[0].app.test_client()
        assert sign_in(client, ('guest', 'hashed-viewer-secret'))['role'] == 'viewer'
        assert client.post('/api/auth/login', json={'username': 'guest', 'password': 'wrong'}).status_code == 401


class TestWhoMayDoWhat:
    def test_everyone_signed_in_can_read(self, accounts):
        client = accounts[2]
        for who in (ADMIN, ANALYST, VIEWER):
            head = headers(client, who)
            for request in READS:
                assert allowed(client, request, head), (who[0], request)

    def test_a_viewer_cannot_analyze_or_upload_or_delete(self, accounts):
        api, system, client = accounts
        head = headers(client, VIEWER)
        for request in WRITES + DELETES:
            assert not allowed(client, request, head), request
        assert system.processed == [] and not getattr(system, 'resets', 0)

    def test_an_analyst_can_analyze_and_upload_but_not_delete(self, accounts):
        api, system, client = accounts
        head = headers(client, ANALYST)
        for request in WRITES:
            assert allowed(client, request, head), request
        assert len(system.processed) == 2
        for request in DELETES:
            assert not allowed(client, request, head), request
        assert not getattr(system, 'resets', 0)

    def test_an_admin_can_do_everything(self, accounts):
        api, system, client = accounts
        head = headers(client, ADMIN)
        for request in WRITES + DELETES:
            assert allowed(client, request, head), request
        assert system.resets == 1

    def test_a_refusal_says_so_and_gives_no_detail(self, accounts):
        client = accounts[2]
        response = client.post('/api/admin/reset-demo-data', json={'confirm': 'RESET'}, headers=headers(client, VIEWER))
        assert response.status_code == 403
        assert response.get_json() == {'error': 'Your account is not allowed to do this'}

    def test_every_route_except_login_and_health_checks_the_role(self, client):
        """No route is left that only checks that a token exists"""
        source = open('api_server.py', encoding='utf-8').read()
        assert '@self._token_required' not in source
        assert source.count('@self._roles(') == 11


class TestTheRoleCannotBeChanged:
    def token(self, secret=TEST_SECRET, **claims):
        claims.setdefault('username', 'someone')
        claims['exp'] = datetime.utcnow() + timedelta(hours=1)
        return {'Authorization': 'Bearer ' + jwt.encode(claims, secret, algorithm='HS256')}

    def test_a_token_without_a_role_is_read_only(self, client):
        head = self.token()
        assert allowed(client, READS[2], head)
        for request in WRITES + DELETES:
            assert not allowed(client, request, head), request

    def test_an_unknown_role_gets_nothing(self, client):
        head = self.token(role='superuser')
        for request in READS + WRITES + DELETES:
            assert not allowed(client, request, head), request

    def test_a_role_that_is_not_text_is_read_only(self, client):
        head = self.token(role=['admin'])
        assert not allowed(client, DELETES[0], head)

    def test_a_token_signed_with_another_key_is_refused_whatever_role_it_claims(self, client):
        head = self.token(secret='some-other-secret-key-of-enough-length-1234', role='admin')
        assert client.post('/api/admin/reset-demo-data', json={'confirm': 'RESET'}, headers=head).status_code == 401

    def test_a_token_that_asks_for_no_signature_is_refused(self, client):
        forged = jwt.encode({'username': 'x', 'role': 'admin'}, key=None, algorithm='none')
        assert client.get('/api/statistics/fraud', headers={'Authorization': f'Bearer {forged}'}).status_code == 401


class TestLockout:
    def fail(self, client, who=ADMIN, n=1):
        return [client.post('/api/auth/login', json={'username': who[0], 'password': 'wrong'}).status_code for _ in range(n)]

    def test_five_wrong_passwords_lock_that_username_even_for_the_right_password(self, accounts):
        api, system, client = accounts
        assert self.fail(client, n=5) == [401] * 5
        refused = client.post('/api/auth/login', json={'username': ADMIN[0], 'password': ADMIN[1]})
        assert refused.status_code == 429
        assert 'Try again in 15 minutes' in refused.get_json()['error'] and int(refused.headers['Retry-After']) > 0

    def test_the_lockout_ends(self, accounts):
        api, system, client = accounts
        now = [1000.0]
        api._clock = lambda: now[0]
        self.fail(client, n=5)
        assert client.post('/api/auth/login', json={'username': ADMIN[0], 'password': ADMIN[1]}).status_code == 429
        now[0] += 14 * 60
        assert client.post('/api/auth/login', json={'username': ADMIN[0], 'password': ADMIN[1]}).status_code == 429
        now[0] += 2 * 60
        assert client.post('/api/auth/login', json={'username': ADMIN[0], 'password': ADMIN[1]}).status_code == 200

    def test_a_successful_sign_in_clears_the_count(self, accounts):
        api, system, client = accounts
        self.fail(client, n=4)
        sign_in(client, ADMIN)
        assert self.fail(client, n=4) == [401] * 4

    def test_the_lockout_is_for_one_username_so_others_can_still_sign_in(self, accounts):
        api, system, client = accounts
        self.fail(client, ADMIN, n=5)
        assert sign_in(client, VIEWER)['role'] == 'viewer'

    def test_an_unknown_username_is_locked_in_the_same_way(self, accounts):
        """So the lockout does not show which usernames exist"""
        api, system, client = accounts
        assert self.fail(client, ('nobody', 'x'), n=5) == [401] * 5
        assert self.fail(client, ('nobody', 'x'), n=1) == [429]

    def test_failed_attempts_that_are_old_do_not_add_up(self, accounts):
        api, system, client = accounts
        now = [0.0]
        api._clock = lambda: now[0]
        self.fail(client, n=4)
        now[0] += 16 * 60
        assert self.fail(client, n=4) == [401] * 4

    def test_the_table_of_failures_stays_small(self, accounts):
        api, system, client = accounts
        now = [0.0]
        api._clock = lambda: now[0]
        for i in range(1100):
            api._record_failure(('203.0.113.1', f'user{i}'))
            now[0] += 1.0
        now[0] += 3600
        api._record_failure(('203.0.113.1', 'one-more'))
        assert len(api._failed_logins) < 1100

class TestDashboardShowsOnlyWhatTheRoleCanUse:
    """The server enforces the role; the dashboard also hides what a role cannot use"""

    def source(self):
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / 'admin-dashboard' / 'script.js').read_text(encoding='utf-8')

    def test_the_sign_in_keeps_the_role_and_signing_out_forgets_it(self):
        source = self.source()
        assert 'sessionStorage.setItem(ROLE_KEY, typeof data.role === "string" ? data.role : "viewer")' in source
        clear = source[source.index('function clearToken'):source.index('// The role comes with the sign-in')]
        assert 'sessionStorage.removeItem(ROLE_KEY)' in clear

    def test_each_role_sees_the_right_panels(self):
        import json
        import shutil
        import subprocess
        node = shutil.which('node')
        if not node:
            pytest.skip('node is not installed')
        source = self.source()
        block = source[source.index('const ROLE_KEY'):source.index('function showToast')]
        script = '''
          const store = {};
          const sessionStorage = {getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; }, removeItem: (k) => { delete store[k]; }};
          const panel = () => ({hidden: false});
          const make = () => { const p = panel(); return {panel: p, closest: () => p}; };
          const el = {analyzeForm: make(), uploadForm: make(), resetForm: make(), roleBadge: {textContent: '', hidden: true}};
        ''' + block + '''
          const seen = {};
          for (const role of ['admin', 'analyst', 'viewer', 'nonsense', null]) {
            if (role === null) delete store[ROLE_KEY]; else store[ROLE_KEY] = role;
            applyRole();
            seen[String(role)] = [!el.analyzeForm.panel.hidden, !el.uploadForm.panel.hidden, !el.resetForm.panel.hidden, el.roleBadge.textContent];
          }
          console.log(JSON.stringify(seen));'''
        out = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=30).stdout.strip()
        assert json.loads(out) == {
            'admin': [True, True, True, 'Admin'],
            'analyst': [True, True, False, 'Analyst'],
            'viewer': [False, False, False, 'Viewer (read-only)'],
            'nonsense': [False, False, False, 'Viewer (read-only)'],      # an unknown or missing role is treated as read-only
            'null': [False, False, False, 'Viewer (read-only)'],
        }

    def test_the_page_has_somewhere_to_show_the_role_and_applies_it_on_opening(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parent.parent / 'admin-dashboard' / 'index.html').read_text(encoding='utf-8')
        assert 'id="roleBadge"' in html
        source = self.source()
        assert source[source.index('function showDashboard'):].split('const REFRESH_SECONDS')[0].count('applyRole();') == 1
