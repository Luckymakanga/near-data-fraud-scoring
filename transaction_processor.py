"""
TRANSACTION PROCESSOR MODULE
Theme 2: Real-Time Fraud Detection Systems
Theme 4: Data Mining and Anomaly Detection Techniques

Handles transaction processing and feature extraction for the ULB credit
card fraud dataset schema (see feature_engineering.py).
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import uuid

from feature_engineering import extract_creditcard_features, PCA_FEATURES

class TransactionProcessor:
    """
    Processes transactions and extracts features for ML model
    Theme 2: Real-time processing
    Theme 4: Data mining and feature engineering
    """

    def __init__(self, db_manager, data_path='data/creditcard_sample.csv'):
        """Initialize processor with database manager"""
        self.db_manager = db_manager
        self.data_path = data_path

    def generate_sample_transactions(self, n=100):
        """
        Draw n real transactions from the credit card fraud training sample
        and assign each to one of this system's demo customers, so the live
        demo exercises the model on the same kind of data it was trained
        on instead of a separately hand-written generator.
        """
        print(f"  Generating {n} sample transactions...")

        df = pd.read_csv(self.data_path)
        sample = df.sample(n=min(n, len(df))).reset_index(drop=True)

        customers = ['CUST001', 'CUST002', 'CUST003', 'CUST004', 'CUST005',
                     'CUST006', 'CUST007', 'CUST008', 'CUST009', 'CUST010']

        transactions = []
        fraud_count = 0

        for _, row in sample.iterrows():
            is_fraud = bool(row['Class'])
            if is_fraud:
                fraud_count += 1

            transaction = {
                'transaction_id': f'TXN{str(uuid.uuid4())[:8].upper()}',
                'customer_id': np.random.choice(customers),
                'amount': float(row['Amount']),
                'Time': float(row['Time']),
                'Amount': float(row['Amount']),
                **{name: float(row[name]) for name in PCA_FEATURES},
                'timestamp': datetime.now() - timedelta(minutes=np.random.randint(0, 1440)),
                'is_fraud_label': is_fraud  # For evaluation only
            }
            transactions.append(transaction)

        print(f"    ✓ Generated {len(transactions) - fraud_count} normal + {fraud_count} fraudulent transactions")

        return transactions

    def extract_features(self, transaction, customer_profile=None):
        """
        Extract features from a transaction for the ML model.
        Theme 4: Data Mining - Feature Engineering

        customer_profile is accepted for interface compatibility with the
        SQL pre-filtering stage but isn't used here - every feature is
        derived directly from the transaction's own PCA components and
        amount (see feature_engineering.extract_creditcard_features).

        Returns:
            Feature array for ML prediction
        """
        return extract_creditcard_features(transaction)
