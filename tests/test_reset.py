"""Starting a new evaluation session: delete all transactions and alerts, and nothing else.

Several people use the live demo in turn, so the dashboard needs a way back to zero. Because
it deletes data permanently, it needs a sign-in, the word RESET in the request, and it is
rate limited and logged."""

import logging

import psycopg2
import pytest

from database_module import DatabaseManager
from test_explain import real

URL = '/api/admin/reset-demo-data'


class TestRoute:
    def reset(self, client, auth, body=None):
        return client.post(URL, json={'confirm': 'RESET'} if body is None else body, headers=auth)

    def test_it_needs_a_sign_in(self, client, system):
        response = client.post(URL, json={'confirm': 'RESET'})
        assert response.status_code == 401 and getattr(system, 'resets', 0) == 0

    @pytest.mark.parametrize('body', [{}, {'confirm': 'reset'}, {'confirm': 'yes'}, {'confirm': True}, {'confirm': 'RESET '}, ['RESET']])
    def test_it_needs_the_exact_word(self, client, auth, system, body):
        response = self.reset(client, auth, body)
        assert response.status_code == 400 and getattr(system, 'resets', 0) == 0

    def test_a_body_that_is_not_json_is_refused(self, client, auth, system):
        response = client.post(URL, data='RESET', headers=auth)
        assert response.status_code == 400 and getattr(system, 'resets', 0) == 0

    def test_it_resets_once_and_reports_how_much_was_removed(self, client, auth, system):
        response = self.reset(client, auth)
        body = response.get_json()
        assert response.status_code == 200 and system.resets == 1
        assert body['removed'] == {'transactions': 7, 'alerts': 2}

    def test_the_reset_is_logged_with_who_did_it(self, client, auth, caplog):
        with caplog.at_level(logging.WARNING):
            self.reset(client, auth)
        assert 'Demo data reset by admin' in caplog.text and '7 transactions and 2 alerts' in caplog.text

    def test_a_get_request_does_not_reset(self, client, auth, system):
        assert client.get(URL, headers=auth).status_code == 405 and getattr(system, 'resets', 0) == 0

    def test_it_can_be_switched_off_on_a_server(self, client, auth, system, monkeypatch):
        monkeypatch.setenv('DEMO_RESET', 'off')
        response = self.reset(client, auth)
        assert response.status_code == 403 and getattr(system, 'resets', 0) == 0

    def test_a_database_failure_is_a_500_without_detail(self, client, auth, system, caplog):
        def broken():
            raise RuntimeError('connection to server at "10.1.2.3" failed: SECRET-DETAIL')
        system.reset_demo_data = broken
        response = self.reset(client, auth)
        assert response.status_code == 500 and 'error_id' in response.get_json()
        assert 'SECRET-DETAIL' not in response.get_data(as_text=True) and 'SECRET-DETAIL' in caplog.text

    def test_it_is_rate_limited(self, client, auth):
        codes = [self.reset(client, auth).status_code for _ in range(12)]
        assert codes[:10] == [200] * 10 and 429 in codes[10:]


class Cursor:
    def __init__(self, conn):
        self.conn, self.rowcount = conn, 0

    def execute(self, sql):
        self.conn.executed.append(sql)
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise psycopg2.Error('boom')
        self.rowcount = self.conn.counts.get(sql.split()[-1], 0)


class Conn:
    def __init__(self, fail_on=None):
        self.executed, self.commits, self.rollbacks, self.fail_on = [], 0, 0, fail_on
        self.counts = {'fraud_alerts': 4, 'transactions': 25}

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class TestDatabase:
    def manager(self, conn):
        m = object.__new__(DatabaseManager)
        m._getconn, m._putconn = (lambda: conn), (lambda c: setattr(conn, 'returned', True))
        return m

    def test_alerts_are_deleted_before_transactions_and_customers_are_untouched(self):
        conn = Conn()
        removed = self.manager(conn).reset_demo_data()
        assert conn.executed == ['DELETE FROM fraud_alerts', 'DELETE FROM transactions']
        assert removed == {'transactions': 25, 'alerts': 4}
        assert conn.commits == 1 and conn.rollbacks == 0 and conn.returned

    def test_a_failure_rolls_back_and_is_raised_not_hidden(self):
        conn = Conn(fail_on='transactions')
        with pytest.raises(psycopg2.Error):
            self.manager(conn).reset_demo_data()
        assert conn.commits == 0 and conn.rollbacks == 1 and conn.returned

    def test_the_system_passes_the_request_to_the_database(self):
        class Db:
            def reset_demo_data(self):
                return {'transactions': 3, 'alerts': 1}

        system = object.__new__(real.FraudDetectionSystem)
        system.db_manager = Db()
        assert system.reset_demo_data() == {'transactions': 3, 'alerts': 1}
