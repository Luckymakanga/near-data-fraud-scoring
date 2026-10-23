"""
DATABASE MODULE
Theme 1: Database Infrastructure and Architecture Foundations

Handles all database operations including:
- Transaction storage
- Customer profiling
- Fraud alerts logging
- SQL query optimization
"""

import os
import time
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json

load_dotenv()

class DatabaseManager:
    """
    Manages PostgreSQL database for fraud detection system
    Implements Theme 1: Database Infrastructure
    """

    def __init__(self, minconn=1, maxconn=10):
        """
        Initialize a pooled PostgreSQL connection, rather than a single
        shared connection, so Flask's request threads each get their own
        connection instead of racing on one cursor.

        Connection details come from the environment (loaded from .env
        locally). If DATABASE_URL is set (the standard connection-string
        format used by Neon, Render, Railway, etc. - e.g.
        postgresql://user:password@host/dbname?sslmode=require) it takes
        priority; otherwise falls back to discrete PGHOST/PGPORT/
        PGDATABASE/PGUSER/PGPASSWORD variables for local dev.
        """
        self._last_used = {}
        database_url = os.environ.get('DATABASE_URL')
        if database_url:
            self.pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn=database_url, **self.KEEPALIVE)
        else:
            self.pool = psycopg2.pool.ThreadedConnectionPool(
                minconn, maxconn,
                host=os.environ.get('PGHOST', 'localhost'),
                port=os.environ.get('PGPORT', '5432'),
                dbname=os.environ.get('PGDATABASE', 'fraud_detection'),
                user=os.environ.get('PGUSER', 'fraud_app'),
                password=os.environ.get('PGPASSWORD'),
                **self.KEEPALIVE
            )

    # Ask the operating system to probe idle connections, so a dropped one is noticed
    KEEPALIVE = {'keepalives': 1, 'keepalives_idle': 30, 'keepalives_interval': 10, 'keepalives_count': 3}

    # A managed database may pause when idle and drop the pool's connections without
    # telling the service. A connection unused for longer than this is tested before
    # it is handed out, and replaced if it is dead.
    CHECK_AFTER_SECONDS = 20
    ATTEMPTS = 3

    def _getconn(self):
        """A usable connection from the pool: one that has been idle is tested first,
        and a dead one is thrown away and replaced instead of failing the request."""
        for attempt in range(self.ATTEMPTS):
            try:
                conn = self.pool.getconn()
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                # opening a new connection failed (for example while a paused database
                # wakes up): wait a moment and try again, and give up on the last try
                if attempt == self.ATTEMPTS - 1:
                    raise
                time.sleep(1 + attempt)
                continue
            idle = time.monotonic() - self._last_used.get(id(conn), 0)
            if not conn.closed and idle < self.CHECK_AFTER_SECONDS:
                return conn
            try:
                if conn.closed:
                    raise psycopg2.InterfaceError('connection is closed')
                with conn.cursor() as cursor:
                    cursor.execute('SELECT 1')
                conn.rollback()  # end the transaction the test started
                return conn
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                self._last_used.pop(id(conn), None)
                self.pool.putconn(conn, close=True)
        return self.pool.getconn()

    def _putconn(self, conn):
        """Return a connection to the pool and note when it was last used"""
        self._last_used[id(conn)] = time.monotonic()
        self.pool.putconn(conn)

    def create_tables(self):
        """Create all necessary database tables with optimized indexes"""
        conn = self._getconn()
        try:
            cursor = conn.cursor()

            # Table 1: Customers (Customer profiles)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    account_type TEXT,
                    created_date TIMESTAMP,
                    avg_transaction REAL,
                    total_balance REAL,
                    last_location TEXT,
                    last_transaction_time TIMESTAMP,
                    unusual_hours_frequency REAL,
                    risk_level TEXT
                )
            ''')

            # Table 2: Transactions (All transactions)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
                    amount REAL NOT NULL,
                    txn_time REAL,
                    timestamp TIMESTAMP,
                    device_id TEXT,
                    ip_address TEXT,
                    fraud_score REAL,
                    is_fraud INTEGER,
                    decision TEXT,
                    status TEXT
                )
            ''')

            # Create indexes for query optimization (Theme 5: SQL Optimization)
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_customer_id ON transactions(customer_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON transactions(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_fraud_score ON transactions(fraud_score)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_amount ON transactions(amount)')

            # Table 3: Fraud Alerts
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fraud_alerts (
                    alert_id SERIAL PRIMARY KEY,
                    transaction_id TEXT NOT NULL REFERENCES transactions(transaction_id),
                    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
                    alert_type TEXT,
                    fraud_score REAL,
                    flags TEXT,
                    alert_time TIMESTAMP,
                    status TEXT,
                    action_taken TEXT
                )
            ''')

            # Table 4: Fraud Detection Logs
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS detection_logs (
                    log_id SERIAL PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    detection_method TEXT,
                    score REAL,
                    timestamp TIMESTAMP,
                    notes TEXT
                )
            ''')

            # Table 5: System Metrics (For Theme 7: Business Impact)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_metrics (
                    metric_id SERIAL PRIMARY KEY,
                    metric_name TEXT,
                    metric_value REAL,
                    timestamp TIMESTAMP,
                    notes TEXT
                )
            ''')

            conn.commit()

            # Insert sample customers (Uganda banking context) - own
            # transaction, after the tables it depends on are committed
            self._insert_sample_customers(conn)

            print("  ✓ Tables created with optimized indexes")
        finally:
            self._putconn(conn)

    def _insert_sample_customers(self, conn):
        """Insert sample customer data. Caller provides the connection."""

        # avg_transaction values are scaled to match the credit card fraud
        # dataset's amount range (mean ~87, 99th percentile ~1,025), not
        # the Uganda-shilling amounts this system used before switching to
        # real training data.
        sample_customers = [
            ('CUST001', 'John Ssemanda', 'Premium', 100, 'Kampala', 0.05, 'NORMAL'),
            ('CUST002', 'Mary Nakamatte', 'Standard', 50, 'Wakiso', 0.10, 'NORMAL'),
            ('CUST003', 'David Okonkwo', 'Standard', 75, 'Kampala', 0.08, 'NORMAL'),
            ('CUST004', 'Grace Kipchoge', 'Premium', 200, 'Kampala', 0.03, 'LOW_RISK'),
            ('CUST005', 'Peter Mwangi', 'Standard', 60, 'Entebbe', 0.12, 'NORMAL'),
            ('CUST006', 'Joyce Nakawuka', 'Standard', 45, 'Kampala', 0.15, 'HIGH_ACTIVITY'),
            ('CUST007', 'Samuel Banda', 'Premium', 150, 'Kampala', 0.04, 'LOW_RISK'),
            ('CUST008', 'Ruth Nyambura', 'Standard', 55, 'Jinja', 0.09, 'NORMAL'),
            ('CUST009', 'Charles Mbewe', 'Standard', 70, 'Kampala', 0.07, 'NORMAL'),
            ('CUST010', 'Patricia Ochieng', 'Premium', 180, 'Kampala', 0.02, 'LOW_RISK'),
        ]

        cursor = conn.cursor()
        for customer_id, name, account_type, avg_trans, location, unusual_freq, risk in sample_customers:
            cursor.execute('''
                INSERT INTO customers
                (customer_id, name, account_type, created_date, avg_transaction,
                 total_balance, last_location, last_transaction_time, unusual_hours_frequency, risk_level)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (customer_id) DO NOTHING
            ''', (customer_id, name, account_type, datetime.now(), avg_trans,
                  avg_trans * 100, location, datetime.now(), unusual_freq, risk))

        conn.commit()

    def log_transaction(self, transaction_data):
        """Log a transaction to database (Theme 1: Database Storage)"""
        conn = self._getconn()
        try:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO transactions
                (transaction_id, customer_id, amount, txn_time,
                 timestamp, fraud_score, is_fraud, decision, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                transaction_data.get('transaction_id'),
                transaction_data.get('customer_id'),
                transaction_data.get('amount'),
                transaction_data.get('txn_time'),
                transaction_data.get('timestamp'),
                transaction_data.get('fraud_score'),
                1 if transaction_data.get('is_fraud') else 0,
                transaction_data.get('decision'),
                'PROCESSED'
            ))
            conn.commit()
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Database error: {e}")
        finally:
            self._putconn(conn)

    def log_fraud_alert(self, alert_data):
        """Log fraud alert (Theme 6: Handling Challenges)"""
        conn = self._getconn()
        try:
            cursor = conn.cursor()
            flags_json = json.dumps(alert_data.get('sql_flags', {}))

            cursor.execute('''
                INSERT INTO fraud_alerts
                (transaction_id, customer_id, alert_type, fraud_score, flags, alert_time, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (
                alert_data.get('transaction_id'),
                alert_data.get('customer_id'),
                'FRAUD_DETECTED',
                alert_data.get('fraud_score'),
                flags_json,
                datetime.now(),
                alert_data.get('decision')
            ))
            conn.commit()
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Database error: {e}")
        finally:
            self._putconn(conn)

    def get_customer_profile(self, customer_id):
        """
        Retrieve customer profile (Theme 4: Data Mining - Behavioral Analysis)
        Uses optimized SQL query with indexes
        """
        conn = self._getconn()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT * FROM customers WHERE customer_id = %s', (customer_id,))
            customer = cursor.fetchone()

            if customer:
                # Get recent transaction history
                cursor.execute('''
                    SELECT decision FROM transactions
                    WHERE customer_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 20
                ''', (customer_id,))

                recent_decisions = [row['decision'] for row in cursor.fetchall() if row['decision']]

                return {
                    'customer_id': customer['customer_id'],
                    'name': customer['name'],
                    'account_type': customer['account_type'],
                    'avg_transaction': customer['avg_transaction'],
                    'last_location': customer['last_location'],
                    'last_transaction_time': customer['last_transaction_time'],
                    'unusual_hours_frequency': customer['unusual_hours_frequency'],
                    'risk_level': customer['risk_level'],
                    'recent_decisions': recent_decisions[:10]
                }
            else:
                # Return default profile for unknown customer
                return {
                    'customer_id': customer_id,
                    'avg_transaction': 100000,
                    'last_location': 'Kampala',
                    'unusual_hours_frequency': 0.1,
                    'recent_decisions': [],
                    'last_transaction_time': datetime.now()
                }
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Error retrieving customer profile: {e}")
            return {}
        finally:
            self._putconn(conn)

    def get_recent_transactions(self, customer_id, minutes=60):
        """
        Get recent transactions for velocity check (Theme 5: SQL Optimization)
        Uses indexed query for fast retrieval
        """
        conn = self._getconn()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cutoff_time = datetime.now() - timedelta(minutes=minutes)

            cursor.execute('''
                SELECT * FROM transactions
                WHERE customer_id = %s AND timestamp > %s
                ORDER BY timestamp DESC
            ''', (customer_id, cutoff_time))

            return [dict(row) for row in cursor.fetchall()]
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Error retrieving recent transactions: {e}")
            return []
        finally:
            self._putconn(conn)

    def get_fraud_statistics(self):
        """Get fraud detection statistics (Theme 7: Business Impact)"""
        conn = self._getconn()
        try:
            cursor = conn.cursor()

            # Total transactions
            cursor.execute('SELECT COUNT(*) FROM transactions')
            total = cursor.fetchone()[0]

            # Fraudulent transactions
            cursor.execute('SELECT COUNT(*) FROM transactions WHERE is_fraud = 1')
            fraud_count = cursor.fetchone()[0]

            # By decision
            cursor.execute('SELECT decision, COUNT(*) FROM transactions GROUP BY decision')
            decisions = cursor.fetchall()

            # Total amount
            cursor.execute('SELECT SUM(amount) FROM transactions')
            total_amount = cursor.fetchone()[0] or 0

            # Fraud amount
            cursor.execute('SELECT SUM(amount) FROM transactions WHERE is_fraud = 1')
            fraud_amount = cursor.fetchone()[0] or 0

            return {
                'total_transactions': total,
                'fraud_count': fraud_count,
                'fraud_rate': fraud_count / total if total > 0 else 0,
                'total_amount': total_amount,
                'fraud_amount': fraud_amount,
                'decisions': dict(decisions) if decisions else {}
            }
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Error getting statistics: {e}")
            return {}
        finally:
            self._putconn(conn)

    def get_all_transactions(self):
        """Retrieve all transactions from database"""
        conn = self._getconn()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute('SELECT * FROM transactions')
            return [dict(row) for row in cursor.fetchall()]
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Error retrieving transactions: {e}")
            return []
        finally:
            self._putconn(conn)

    def get_latest_transactions(self, limit=50, decision=None):
        """
        Retrieve the most recent transactions, newest first (for dashboard display).
        Pass decision ('BLOCK', 'REVIEW', 'MONITOR', or 'ALLOW') to filter to just that outcome.
        """
        conn = self._getconn()
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            if decision:
                cursor.execute('''
                    SELECT * FROM transactions
                    WHERE decision = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                ''', (decision, limit))
            else:
                cursor.execute('''
                    SELECT * FROM transactions
                    ORDER BY timestamp DESC
                    LIMIT %s
                ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except psycopg2.Error as e:
            conn.rollback()
            print(f"Error retrieving latest transactions: {e}")
            return []
        finally:
            self._putconn(conn)

    def reset_demo_data(self):
        """Delete every stored transaction and alert, keeping the customers, in one step.

        Alerts go first because they refer to transactions. Either both tables are cleared or
        neither is. Returns how many rows were removed from each."""
        conn = self._getconn()
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM fraud_alerts')
            alerts = cursor.rowcount
            cursor.execute('DELETE FROM transactions')
            transactions = cursor.rowcount
            conn.commit()
            return {'transactions': transactions, 'alerts': alerts}
        except psycopg2.Error:
            conn.rollback()
            raise
        finally:
            self._putconn(conn)

    def close(self):
        """Close all pooled database connections. Safe to call more than once."""
        if getattr(self, 'pool', None) and not self.pool.closed:
            self.pool.closeall()

    def __del__(self):
        """Cleanup on deletion"""
        self.close()
