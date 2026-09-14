"""
TRANSACTION PROCESSOR MODULE
Theme 2: Real-Time Fraud Detection Systems
Theme 4: Data Mining and Anomaly Detection Techniques

Handles transaction processing, feature extraction, and data mining
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import uuid

class TransactionProcessor:
    """
    Processes transactions and extracts features for ML model
    Theme 2: Real-time processing
    Theme 4: Data mining and feature engineering
    """
    
    def __init__(self, db_manager):
        """Initialize processor with database manager"""
        self.db_manager = db_manager
        
        # Uganda banking context
        self.common_merchants = [
            'Supermarket', 'Petrol Station', 'Restaurant', 'Mobile Money', 
            'Pharmacy', 'Utility Payment', 'School Fee', 'Hospital',
            'Grocery', 'Hardware', 'Clothing', 'Entertainment'
        ]
        
        self.uganda_locations = [
            'Kampala', 'Wakiso', 'Entebbe', 'Jinja', 'Masaka',
            'Mbale', 'Kigali', 'Mbarara', 'Fort Portal', 'Soroti'
        ]
    
    def generate_sample_transactions(self, n=100):
        """
        Generate sample transactions for testing
        Simulates realistic Uganda banking transactions
        """
        print(f"  Generating {n} sample transactions...")
        
        transactions = []
        customers = ['CUST001', 'CUST002', 'CUST003', 'CUST004', 'CUST005',
                     'CUST006', 'CUST007', 'CUST008', 'CUST009', 'CUST010']
        
        fraud_count = 0
        normal_count = 0
        
        for i in range(n):
            # Determine if transaction should be fraudulent (~3-5% fraud rate)
            is_fraud = np.random.random() < 0.04
            
            customer_id = np.random.choice(customers)
            
            if is_fraud:
                fraud_count += 1
                # Fraudulent characteristics
                amount = np.random.uniform(500000, 10000000)  # Large amounts
                merchant = 'Unknown Merchant'
                location = np.random.choice([x for x in self.uganda_locations if x != 'Kampala'])
                hour = np.random.choice([0, 1, 2, 3, 22, 23])  # Unusual hours
            else:
                normal_count += 1
                # Normal characteristics
                amount = np.random.lognormal(10, 1.5)  # Log-normal distribution
                merchant = np.random.choice(self.common_merchants)
                location = 'Kampala'  # Most transactions in capital
                hour = np.random.choice(range(8, 18))  # Business hours
            
            transaction = {
                'transaction_id': f'TXN{str(uuid.uuid4())[:8].upper()}',
                'customer_id': customer_id,
                'amount': amount,
                'merchant_category': merchant,
                'location': location,
                'device_id': f'DEV{np.random.randint(100, 999)}',
                'ip_address': f'192.168.{np.random.randint(0,255)}.{np.random.randint(0,255)}',
                'timestamp': datetime.now() - timedelta(minutes=np.random.randint(0, 1440)),
                'hour': hour,
                'is_fraud_label': is_fraud  # For evaluation only
            }
            
            transactions.append(transaction)
        
        print(f"    ✓ Generated {normal_count} normal + {fraud_count} fraudulent transactions")
        
        return transactions
    
    def extract_features(self, transaction, customer_profile):
        """
        Extract features from transaction for ML model
        Theme 4: Data Mining - Feature Engineering
        
        Args:
            transaction: Transaction data dictionary
            customer_profile: Customer profile from database
            
        Returns:
            Feature array for ML prediction
        """
        
        # Feature 1: Transaction amount (normalized by customer avg)
        amount = transaction['amount']
        avg_amount = customer_profile.get('avg_transaction', 100000)
        amount_ratio = min(amount / avg_amount, 10)  # Cap at 10x
        
        # Feature 2: Customer age (proxy: days since account creation)
        customer_age = np.random.uniform(0, 15)  # Years
        
        # Feature 3: Account tenure
        account_tenure = np.random.uniform(0, 20)  # Years
        
        # Feature 4: Transaction frequency (recent)
        recent_transactions = self.db_manager.get_recent_transactions(
            transaction['customer_id'],
            minutes=30
        )
        transaction_frequency = len(recent_transactions)
        
        # Feature 5: Average transaction size variance
        avg_transaction_size = customer_profile.get('avg_transaction', 100000)
        size_variance = abs(amount - avg_transaction_size) / max(avg_transaction_size, 1)
        
        # Feature 6: Location risk (Theme 4: Behavioral Analysis)
        location_risk = 0.1  # Low risk for normal locations
        if transaction['location'] not in ['Kampala', 'Wakiso']:
            location_risk = 0.5  # Higher risk for unusual locations
        
        # Feature 7: Time risk (Theme 4: Temporal Analysis)
        hour = transaction.get('hour', datetime.now().hour)
        time_risk = 0.2 if 6 <= hour <= 22 else 0.8  # High risk for off-hours
        
        # Feature 8: Merchant risk (Theme 4: Merchant Pattern Analysis)
        merchant_risk = 0.1
        if transaction['merchant_category'] not in customer_profile.get('usual_merchants', []):
            merchant_risk = 0.6
        if transaction['merchant_category'] == 'Unknown Merchant':
            merchant_risk = 0.9
        
        # Feature 9: Device consistency
        device_consistency = 0.8  # Assume mostly consistent
        
        # Feature 10: Velocity score (multiple transactions in short time)
        velocity_score = min(transaction_frequency / 5, 1.0)  # Normalized
        
        # Combine into feature vector
        features = np.array([
            amount_ratio,           # Feature 1
            customer_age,           # Feature 2
            account_tenure,         # Feature 3
            transaction_frequency,  # Feature 4
            size_variance,          # Feature 5
            location_risk,          # Feature 6
            time_risk,              # Feature 7
            merchant_risk,          # Feature 8
            device_consistency,     # Feature 9
            velocity_score          # Feature 10
        ])
        
        return features
    
    def detect_anomalies(self, customer_id, transaction):
        """
        Detect anomalies using statistical methods
        Theme 4: Anomaly Detection
        
        Returns:
            Dictionary with anomaly scores
        """
        anomalies = {
            'amount_anomaly': 0.0,
            'location_anomaly': 0.0,
            'time_anomaly': 0.0,
            'merchant_anomaly': 0.0
        }
        
        customer_profile = self.db_manager.get_customer_profile(customer_id)
        
        # Amount anomaly (Z-score based)
        amount = transaction['amount']
        avg = customer_profile.get('avg_transaction', 100000)
        amount_zscore = abs((amount - avg) / max(avg * 0.5, 1))
        anomalies['amount_anomaly'] = min(amount_zscore / 3, 1.0)  # Normalize
        
        # Location anomaly
        usual_location = customer_profile.get('last_location', 'Kampala')
        if transaction['location'] != usual_location:
            anomalies['location_anomaly'] = 0.7
        
        # Time anomaly
        hour = transaction.get('hour', datetime.now().hour)
        if hour < 6 or hour > 22:
            if customer_profile.get('unusual_hours_frequency', 0.1) < 0.2:
                anomalies['time_anomaly'] = 0.6
        
        # Merchant anomaly
        if transaction['merchant_category'] not in customer_profile.get('usual_merchants', []):
            anomalies['merchant_anomaly'] = 0.5
        
        return anomalies
    
    def calculate_behavioral_score(self, customer_id, transaction):
        """
        Calculate behavioral deviation score
        Theme 4: Behavioral Analysis
        
        Returns:
            Behavioral score 0-1
        """
        customer_profile = self.db_manager.get_customer_profile(customer_id)
        
        deviations = 0
        total_checks = 4
        
        # Check 1: Amount deviation
        amount = transaction['amount']
        avg = customer_profile.get('avg_transaction', 100000)
        if amount > avg * 3:
            deviations += 1
        
        # Check 2: Location deviation
        if transaction['location'] != customer_profile.get('last_location', 'Kampala'):
            deviations += 1
        
        # Check 3: Merchant deviation
        if transaction['merchant_category'] not in customer_profile.get('usual_merchants', []):
            deviations += 1
        
        # Check 4: Time deviation
        hour = transaction.get('hour', datetime.now().hour)
        if hour < 6 or hour > 22:
            if customer_profile.get('unusual_hours_frequency', 0.1) < 0.2:
                deviations += 1
        
        behavioral_score = deviations / total_checks
        
        return behavioral_score
