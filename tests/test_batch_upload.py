"""Batch uploads: shared reads, row-level failures, timing, and chunk-friendly limits.

On a free host the database is far away, so each of the roughly ten round trips a row
made cost real time: 100 rows took about 70 seconds at 60 ms of distance and 500 rows ran
past the server's and the host's time limits. A batch now reads each customer's profile and
hourly count once, a failing row no longer cancels the batch, and the response reports how
long it took."""

import pytest

from test_explain import StubProcessor, make_model, real

GOOD = {'transaction_id': 'T0', 'customer_id': 'CUST001', 'amount': 10}


def txns(n, customers=('CUST001', 'CUST002', 'CUST003')):
    return [{'transaction_id': f'T{i}', 'customer_id': customers[i % len(customers)], 'amount': 10 + i, 'Time': 12 * 3600} for i in range(n)]


# ---------------------------------------------------------------- the API route

class TestRoute:
    def post(self, client, auth, rows):
        return client.post('/api/transactions/batch-analyze', json={'transactions': rows}, headers=auth)

    def test_every_row_shares_one_batch_context(self, client, auth, system):
        self.post(client, auth, txns(7))
        assert system.batches == 1
        assert len({id(b) for b in system.batch_seen}) == 1 and system.batch_seen[0] is not None

    def test_the_response_reports_how_long_it_took(self, client, auth):
        summary = self.post(client, auth, txns(5)).get_json()['summary']
        assert summary['total'] == 5 and summary['stopped_early'] is False
        assert isinstance(summary['elapsed_seconds'], float) and summary['elapsed_seconds'] >= 0

    def test_a_failing_row_does_not_cancel_the_rest(self, client, auth, system, caplog):
        original = system.process_transaction

        def flaky(txn, explain=False, batch=None):
            if txn['transaction_id'] == 'T2':
                raise RuntimeError('connection to server at "10.1.2.3" failed: SECRET-DETAIL')
            return original(txn, explain, batch)

        system.process_transaction = flaky
        response = self.post(client, auth, txns(6))
        body = response.get_json()
        assert response.status_code == 200
        assert body['summary']['total'] == 5 and len(body['errors']) == 1
        assert body['errors'][0]['index'] == 2 and 'reference' in body['errors'][0]['error']
        assert 'SECRET-DETAIL' not in response.get_data(as_text=True)     # the detail stays in the log
        assert 'SECRET-DETAIL' in caplog.text

    def test_three_failures_in_a_row_stop_the_batch(self, client, auth, system):
        calls = []

        def broken(txn, explain=False, batch=None):
            calls.append(txn['transaction_id'])
            raise RuntimeError('database is down')

        system.process_transaction = broken
        body = self.post(client, auth, txns(10)).get_json()
        assert len(calls) == 3                                   # no point trying the other seven
        assert body['summary']['stopped_early'] is True and body['summary']['total'] == 0
        assert len(body['errors']) == 3

    def test_a_success_resets_the_run_of_failures(self, client, auth, system):
        original = system.process_transaction
        failing = {'T1', 'T2', 'T4', 'T5'}

        def flaky(txn, explain=False, batch=None):
            if txn['transaction_id'] in failing:
                raise RuntimeError('hiccup')
            return original(txn, explain, batch)

        system.process_transaction = flaky
        body = self.post(client, auth, txns(8)).get_json()
        assert body['summary']['stopped_early'] is False and body['summary']['total'] == 4

    def test_invalid_rows_are_still_skipped_with_a_reason(self, client, auth):
        rows = txns(3) + [{'transaction_id': '<script>', 'customer_id': 'CUST001', 'amount': 1}]
        body = self.post(client, auth, rows).get_json()
        assert body['summary']['total'] == 3 and body['errors'][0]['index'] == 3

    def test_a_dashboard_sized_series_of_chunks_is_allowed(self, client, auth):
        """A 500-row file goes up as ten chunks of 50; several uploads in an hour must work"""
        codes = {self.post(client, auth, txns(1)).status_code for _ in range(60)}
        assert codes == {200}

    def test_the_limit_on_chunks_still_exists(self, client, auth):
        codes = [self.post(client, auth, txns(1)).status_code for _ in range(205)]
        assert 429 in codes[200:]


# ---------------------------------------------------------------- the scoring side

class CountingDb:
    """Stores what is logged and counts reads, like the real database would"""

    def __init__(self, existing=None):
        self.logged = {c: list(range(n)) for c, n in (existing or {}).items()}
        self.profile_reads = self.recent_reads = 0

    def get_customer_profile(self, customer_id):
        self.profile_reads += 1
        return {'avg_transaction': 100.0, 'unusual_hours_frequency': 0.05}

    def get_recent_transactions(self, customer_id, minutes):
        self.recent_reads += 1
        return list(self.logged.get(customer_id, []))

    def log_transaction(self, result):
        self.logged.setdefault(result['customer_id'], []).append(result['transaction_id'])

    def log_fraud_alert(self, result):
        pass


def system_with(db):
    system = object.__new__(real.FraudDetectionSystem)
    system.db_manager, system.transaction_processor, system.ml_model = db, StubProcessor(), make_model()
    return system


def run(db, rows, batched):
    system = system_with(db)
    batch = system.start_batch() if batched else None
    out = []
    for row in rows:
        result = system.process_transaction(dict(row), batch=batch) if batched else system.process_transaction(dict(row))
        out.append((result['sql_flags'], result['decision'], result['fraud_score']))
    return out


class TestSharedReads:
    def test_a_batch_reads_each_customers_profile_and_count_once(self):
        db = CountingDb()
        run(db, txns(30), batched=True)
        assert db.profile_reads == 3 and db.recent_reads == 3

    def test_without_a_batch_every_row_reads_them(self):
        db = CountingDb()
        run(db, txns(30), batched=False)
        assert db.profile_reads == 30 and db.recent_reads == 30

    def test_decisions_and_flags_are_identical_with_and_without_the_shared_reads(self):
        rows = txns(40, customers=('CUST001', 'CUST002'))
        assert run(CountingDb(), rows, batched=True) == run(CountingDb(), rows, batched=False)

    def test_the_hourly_count_still_crosses_its_limit_on_the_same_row(self):
        """A customer with 8 transactions already: the velocity rule (more than 10) must
        fire from the 4th new row onward, exactly as when the count is read every time"""
        rows = txns(8, customers=('CUST001',))
        shared = run(CountingDb({'CUST001': 8}), rows, batched=True)
        every_time = run(CountingDb({'CUST001': 8}), rows, batched=False)
        assert shared == every_time
        fired = [flags['velocity_anomaly'] for flags, _, _ in shared]
        assert fired == [False, False, False, True, True, True, True, True]

    def test_the_context_is_not_shared_between_batches(self):
        system = system_with(CountingDb())
        assert system.start_batch() is not system.start_batch()
