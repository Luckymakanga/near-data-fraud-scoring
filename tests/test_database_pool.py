"""The database layer recovers from connections that went stale while the database was idle.

A managed database may pause when idle and drop the service's pooled connections without
telling it. The first requests afterwards used to fail with a 500 (the dashboard showed
"Internal server error" right after sign-in). Idle connections are now tested before use
and replaced if dead. These tests use stand-in connections, so no database is needed."""

import re
import time
from pathlib import Path

import psycopg2
import pytest

import database_module
from database_module import DatabaseManager

ROOT = Path(__file__).resolve().parent.parent


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self.conn.executed.append(sql)
        if self.conn.dead:
            raise psycopg2.OperationalError('server closed the connection unexpectedly')


class FakeConn:
    def __init__(self, dead=False, closed=0):
        self.dead, self.closed = dead, closed
        self.executed, self.rollbacks = [], 0

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1


class FakePool:
    """Hands out the given connections in order, then fresh healthy ones"""

    closed = True   # so that the manager's clean-up has nothing to close

    def __init__(self, conns, connect_failures=0):
        self.queue, self.returned, self.connect_failures = list(conns), [], connect_failures

    def getconn(self):
        if self.connect_failures:
            self.connect_failures -= 1
            raise psycopg2.OperationalError('could not connect: the database is waking up')
        return self.queue.pop(0) if self.queue else FakeConn()

    def putconn(self, conn, close=False):
        self.returned.append((conn, close))


def manager(pool):
    m = object.__new__(DatabaseManager)
    m.pool, m._last_used = pool, {}
    return m


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(database_module.time, 'sleep', lambda s: None)


class TestBorrowing:
    def test_a_recently_used_connection_is_handed_out_without_a_test(self):
        conn = FakeConn()
        m = manager(FakePool([conn]))
        m._last_used[id(conn)] = time.monotonic()
        assert m._getconn() is conn
        assert conn.executed == []

    def test_an_idle_connection_is_tested_and_kept_if_it_works(self):
        conn = FakeConn()
        m = manager(FakePool([conn]))
        m._last_used[id(conn)] = time.monotonic() - 600
        assert m._getconn() is conn
        assert conn.executed == ['SELECT 1'] and conn.rollbacks == 1

    def test_a_connection_never_used_before_is_tested(self):
        conn = FakeConn()
        assert manager(FakePool([conn]))._getconn() is conn
        assert conn.executed == ['SELECT 1']

    def test_a_dead_idle_connection_is_thrown_away_and_replaced(self):
        dead, fresh = FakeConn(dead=True), FakeConn()
        pool = FakePool([dead, fresh])
        m = manager(pool)
        m._last_used[id(dead)] = time.monotonic() - 600
        assert m._getconn() is fresh
        assert (dead, True) in pool.returned          # discarded, not returned for reuse
        assert id(dead) not in m._last_used

    def test_a_closed_connection_is_thrown_away(self):
        closed, fresh = FakeConn(closed=2), FakeConn()
        pool = FakePool([closed, fresh])
        assert manager(pool)._getconn() is fresh
        assert (closed, True) in pool.returned

    def test_several_dead_connections_in_a_row_are_all_replaced(self):
        dead = [FakeConn(dead=True), FakeConn(dead=True)]
        fresh = FakeConn()
        assert manager(FakePool(dead + [fresh]))._getconn() is fresh

    def test_when_every_attempt_finds_a_dead_connection_a_new_one_is_opened(self):
        dead = [FakeConn(dead=True) for _ in range(DatabaseManager.ATTEMPTS)]
        pool = FakePool(dead)
        conn = manager(pool)._getconn()
        assert conn not in dead and not conn.dead

    def test_opening_a_connection_is_retried_while_the_database_wakes(self):
        pool = FakePool([FakeConn()], connect_failures=2)
        assert manager(pool)._getconn() is not None

    def test_it_gives_up_if_the_database_never_answers(self):
        pool = FakePool([], connect_failures=10)
        with pytest.raises(psycopg2.OperationalError):
            manager(pool)._getconn()

    def test_returning_a_connection_notes_when_it_was_used(self):
        conn, pool = FakeConn(), FakePool([])
        m = manager(pool)
        m._putconn(conn)
        assert pool.returned == [(conn, False)]
        assert time.monotonic() - m._last_used[id(conn)] < 5


class TestSetUp:
    @pytest.mark.parametrize('url', ['postgresql://u:p@host/db?sslmode=require', None])
    def test_keepalive_settings_reach_the_pool(self, monkeypatch, url):
        seen = {}

        class Capturing:
            def __init__(self, minconn, maxconn, *args, **kwargs):
                seen.update(kwargs)

        monkeypatch.setattr(database_module.psycopg2.pool, 'ThreadedConnectionPool', Capturing)
        if url:
            monkeypatch.setenv('DATABASE_URL', url)
        else:
            monkeypatch.delenv('DATABASE_URL', raising=False)
        DatabaseManager()
        assert seen['keepalives'] == 1 and seen['keepalives_idle'] == 30

    def test_no_method_borrows_a_connection_without_the_check(self):
        """Every borrow goes through _getconn and every return through _putconn"""
        source = (ROOT / 'database_module.py').read_text(encoding='utf-8')
        body = source.split('def create_tables')[1]
        assert 'self.pool.getconn()' not in body
        assert 'self.pool.putconn(' not in body
        assert len(re.findall(r'self\._getconn\(\)', body)) == len(re.findall(r'self\._putconn\(conn\)', body))
