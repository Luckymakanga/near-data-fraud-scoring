"""
DATABASE MODULE
Theme 1: Database Infrastructure and Architecture Foundations

Handles all database operations including:
- Transaction storage
- Customer profiling
- Fraud alerts logging
- SQL query optimization
"""

import sqlite3
import pandas as pd
import threading
from datetime import datetime, timedelta
import json

class DatabaseManager:
    """
    Manages SQLite database for fraud detection system
    Implements Theme 1: Database Infrastructure
    """

    def __init__(self, db_path='fraud_detection.db'):
        """Initialize database connection"""
        self.db_path = db_path
        self.connection = None
        # A single sqlite3.Cursor is shared across all callers, and Flask's
        # dev server can handle requests on multiple threads concurrently.
        # Concurrent cursor.execute() calls on the same cursor race on its
        # internal C state and can crash the interpreter, so every query
        # below is serialized through this lock.
        self._lock = threading.Lock()
        self._connect()
    
    def _connect(self):
        """Create database connection"""
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.cursor = self.connection.cursor()
    
    def create_tables(self):
        """Create all necessary database tables with optimized indexes"""
        with self._lock:
            # Table 1: Customers (Customer profiles)
            self.cursor.execute('''
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
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    amount REAL NOT NULL,
                    txn_time REAL,
                    timestamp TIMESTAMP,
                    device_id TEXT,
                    ip_address TEXT,
                    fraud_score REAL,
                    is_fraud INTEGER,
                    decision TEXT,
                    status TEXT,
                    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
                )
            ''')

            # Create indexes for query optimization (Theme 5: SQL Optimization)
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_customer_id ON transactions(customer_id)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON transactions(timestamp)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_fraud_score ON transactions(fraud_score)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_amount ON transactions(amount)')

            # Table 3: Fraud Alerts
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS fraud_alerts (
                    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    alert_type TEXT,
                    fraud_score REAL,
                    flags TEXT,
                    alert_time TIMESTAMP,
                    status TEXT,
                    action_taken TEXT,
                    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id),
                    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
                )
            ''')

            # Table 4: Fraud Detection Logs
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS detection_logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id TEXT NOT NULL,
                    detection_method TEXT,
                    score REAL,
                    timestamp TIMESTAMP,
                    notes TEXT
                )
            ''')

            # Table 5: System Metrics (For Theme 7: Business Impact)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_metrics (
                    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT,
                    metric_value REAL,
                    timestamp TIMESTAMP,
                    notes TEXT
                )
            ''')

            # Insert sample customers (Uganda banking context)
            self._insert_sample_customers_locked()

            self.connection.commit()
            print("  ✓ Tables created with optimized indexes")

    def _insert_sample_customers_locked(self):
        """Insert sample customer data. Caller must already hold self._lock."""

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

        for customer_id, name, account_type, avg_trans, location, unusual_freq, risk in sample_customers:
            try:
                self.cursor.execute('''
                    INSERT OR IGNORE INTO customers
                    (customer_id, name, account_type, created_date, avg_transaction,
                     total_balance, last_location, last_transaction_time, unusual_hours_frequency, risk_level)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (customer_id, name, account_type, datetime.now(), avg_trans,
                      avg_trans * 100, location, datetime.now(), unusual_freq, risk))
            except sqlite3.Error:
                pass

        self.connection.commit()
    
    def log_transaction(self, transaction_data):
        """Log a transaction to database (Theme 1: Database Storage)"""
        with self._lock:
            try:
                self.cursor.execute('''
                    INSERT INTO transactions
                    (transaction_id, customer_id, amount, txn_time,
                     timestamp, fraud_score, is_fraud, decision, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                self.connection.commit()
            except sqlite3.Error as e:
                print(f"Database error: {e}")

    def log_fraud_alert(self, alert_data):
        """Log fraud alert (Theme 6: Handling Challenges)"""
        with self._lock:
            try:
                flags_json = json.dumps(alert_data.get('sql_flags', {}))

                self.cursor.execute('''
                    INSERT INTO fraud_alerts
                    (transaction_id, customer_id, alert_type, fraud_score, flags, alert_time, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    alert_data.get('transaction_id'),
                    alert_data.get('customer_id'),
                    'FRAUD_DETECTED',
                    alert_data.get('fraud_score'),
                    flags_json,
                    datetime.now(),
                    alert_data.get('decision')
                ))
                self.connection.commit()
            except sqlite3.Error as e:
                print(f"Database error: {e}")
    
    def get_customer_profile(self, customer_id):
        """
        Retrieve customer profile (Theme 4: Data Mining - Behavioral Analysis)
        Uses optimized SQL query with indexes
        """
        with self._lock:
            try:
                self.cursor.execute('SELECT * FROM customers WHERE customer_id = ?', (customer_id,))
                customer = self.cursor.fetchone()

                if customer:
                    # Get recent transaction history
                    self.cursor.execute('''
                        SELECT decision FROM transactions
                        WHERE customer_id = ?
                        ORDER BY timestamp DESC
                        LIMIT 20
                    ''', (customer_id,))

                    recent_decisions = [row[0] for row in self.cursor.fetchall() if row[0]]

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
            except sqlite3.Error as e:
                print(f"Error retrieving customer profile: {e}")
                return {}
    
    def get_recent_transactions(self, customer_id, minutes=60):
        """
        Get recent transactions for velocity check (Theme 5: SQL Optimization)
        Uses indexed query for fast retrieval
        """
        with self._lock:
            try:
                cutoff_time = datetime.now() - timedelta(minutes=minutes)

                self.cursor.execute('''
                    SELECT * FROM transactions
                    WHERE customer_id = ? AND timestamp > ?
                    ORDER BY timestamp DESC
                ''', (customer_id, cutoff_time.isoformat()))

                transactions = self.cursor.fetchall()
                return [dict(row) for row in transactions]
            except sqlite3.Error as e:
                print(f"Error retrieving recent transactions: {e}")
                return []
    
    def get_fraud_statistics(self):
        """Get fraud detection statistics (Theme 7: Business Impact)"""
        with self._lock:
            try:
                # Total transactions
                self.cursor.execute('SELECT COUNT(*) FROM transactions')
                total = self.cursor.fetchone()[0]

                # Fraudulent transactions
                self.cursor.execute('SELECT COUNT(*) FROM transactions WHERE is_fraud = 1')
                fraud_count = self.cursor.fetchone()[0]

                # By decision
                self.cursor.execute('SELECT decision, COUNT(*) FROM transactions GROUP BY decision')
                decisions = self.cursor.fetchall()

                # Total amount
                self.cursor.execute('SELECT SUM(amount) FROM transactions')
                total_amount = self.cursor.fetchone()[0] or 0

                # Fraud amount
                self.cursor.execute('SELECT SUM(amount) FROM transactions WHERE is_fraud = 1')
                fraud_amount = self.cursor.fetchone()[0] or 0

                return {
                    'total_transactions': total,
                    'fraud_count': fraud_count,
                    'fraud_rate': fraud_count / total if total > 0 else 0,
                    'total_amount': total_amount,
                    'fraud_amount': fraud_amount,
                    'decisions': dict(decisions) if decisions else {}
                }
            except sqlite3.Error as e:
                print(f"Error getting statistics: {e}")
                return {}
    
    def get_all_transactions(self):
        """Retrieve all transactions from database"""
        with self._lock:
            try:
                self.cursor.execute('SELECT * FROM transactions')
                columns = [description[0] for description in self.cursor.description]

                transactions = []
                for row in self.cursor.fetchall():
                    transactions.append(dict(zip(columns, row)))

                return transactions
            except sqlite3.Error as e:
                print(f"Error retrieving transactions: {e}")
                return []

    def get_latest_transactions(self, limit=50, decision=None):
        """
        Retrieve the most recent transactions, newest first (for dashboard display).
        Pass decision ('BLOCK', 'REVIEW', 'MONITOR', or 'ALLOW') to filter to just that outcome.
        """
        with self._lock:
            try:
                if decision:
                    self.cursor.execute('''
                        SELECT * FROM transactions
                        WHERE decision = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    ''', (decision, limit))
                else:
                    self.cursor.execute('''
                        SELECT * FROM transactions
                        ORDER BY timestamp DESC
                        LIMIT ?
                    ''', (limit,))
                columns = [description[0] for description in self.cursor.description]
                return [dict(zip(columns, row)) for row in self.cursor.fetchall()]
            except sqlite3.Error as e:
                print(f"Error retrieving latest transactions: {e}")
                return []

    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
    
    def __del__(self):
        """Cleanup on deletion"""
        self.close()
