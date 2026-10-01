"""
UGANDA BANKING SECTOR FRAUD DETECTION SYSTEM
Machine Learning-Integrated Database System
For detecting financial fraud in real-time

Main Application Module
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    # Windows consoles default to a legacy codepage (e.g. cp1252) that can't
    # encode the checkmark/emoji characters this system prints.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import json
from pathlib import Path

# Import custom modules
from database_module import DatabaseManager
from advanced_ml_models import AdvancedFraudDetectionModel
from transaction_processor import TransactionProcessor
from analytics import FraudAnalytics

class FraudDetectionSystem:
    """
    Complete integrated fraud detection system for Uganda's banking sector
    Combines database technology with machine learning for real-time fraud detection
    """
    
    def __init__(self, db_path='fraud_detection.db', model_path='fraud_model.pkl'):
        """
        Initialize the fraud detection system
        
        Args:
            db_path: Path to SQLite database
            model_path: Path to save/load ML model
        """
        print("=" * 80)
        print("UGANDA BANKING SECTOR - FRAUD DETECTION SYSTEM")
        print("Powered by Machine Learning & Database Technology")
        print("=" * 80)
        
        self.db_path = db_path
        self.model_path = model_path
        
        # Initialize core modules
        print("\n[1/4] Initializing Database Manager...")
        self.db_manager = DatabaseManager(db_path)
        
        print("[2/4] Initializing Machine Learning Model...")
        self.ml_model = AdvancedFraudDetectionModel(model_path)
        
        print("[3/4] Initializing Transaction Processor...")
        self.transaction_processor = TransactionProcessor(self.db_manager)
        
        print("[4/4] Initializing Analytics Engine...")
        self.analytics = FraudAnalytics(self.db_manager)
        
        print("\n✓ System initialized successfully!\n")
    
    def setup_system(self):
        """Setup the system - create tables and prepare database"""
        print("\n" + "=" * 80)
        print("SETTING UP SYSTEM")
        print("=" * 80)
        
        # Create database tables
        print("\n[Step 1] Creating database tables...")
        self.db_manager.create_tables()
        print("✓ Database tables created")
        
        # Train the ML model with sample data
        print("\n[Step 2] Training machine learning model...")
        self.ml_model.train_ensemble_model()
        print("✓ ML model trained and ready")
        
        # Generate sample transactions
        print("\n[Step 3] Generating sample transaction data...")
        sample_transactions = self.transaction_processor.generate_sample_transactions(n=500)
        print(f"✓ Generated {len(sample_transactions)} sample transactions")
        
        return sample_transactions
    
    def process_transaction(self, transaction_data):
        """
        Process a single transaction in real-time
        
        THEME 2: Real-Time Processing
        - Immediate fraud assessment
        - Sub-second detection latency
        
        Args:
            transaction_data: Dictionary with transaction details
            
        Returns:
            Dictionary with fraud detection results
        """
        # Validate transaction
        if not self._validate_transaction(transaction_data):
            return {'status': 'ERROR', 'message': 'Invalid transaction data'}
        
        # Get customer profile (Behavioral Analysis - Theme 4)
        customer_id = transaction_data['customer_id']
        customer_profile = self.db_manager.get_customer_profile(customer_id)
        
        # Perform SQL-based pre-filtering (Theme 5)
        sql_flags = self._perform_sql_filtering(transaction_data, customer_profile)
        
        # Prepare features for ML model (Theme 3)
        features = self.transaction_processor.extract_features(
            transaction_data, 
            customer_profile
        )
        
        # Get ML fraud prediction (Theme 3: Machine Learning)
        # Cast to native Python types - numpy.float64/numpy.bool_ aren't JSON serializable
        fraud_probability = float(self.ml_model.predict_fraud_advanced(features))
        is_fraud = bool(fraud_probability > 0.5)
        
        # Combine SQL flags and ML prediction (Theme 6: Handling Challenges)
        final_decision = self._combine_detections(sql_flags, is_fraud, fraud_probability)
        
        # Store results in database
        result = {
            'transaction_id': transaction_data.get('transaction_id'),
            'customer_id': customer_id,
            'timestamp': datetime.now().isoformat(),
            'amount': transaction_data['amount'],
            'txn_time': transaction_data.get('Time'),
            'fraud_score': fraud_probability,
            'is_fraud': is_fraud,
            'decision': final_decision,
            'sql_flags': sql_flags,
            'confidence': fraud_probability if is_fraud else 1 - fraud_probability
        }
        
        # Log transaction
        self.db_manager.log_transaction(result)
        
        # If fraud detected, take action
        if is_fraud or final_decision == 'BLOCK':
            self.db_manager.log_fraud_alert(result)
            print(f"\n⚠️ FRAUD ALERT: Transaction {result['transaction_id']} flagged")
            print(f"   Amount: {result['amount']} UGX")
            print(f"   Fraud Score: {fraud_probability:.2%}")
            print(f"   Decision: {final_decision}")
        
        return result
    
    def batch_process_transactions(self, transactions):
        """
        Process multiple transactions efficiently (Theme 2: Real-Time Batch Processing)
        
        Args:
            transactions: List of transaction dictionaries
            
        Returns:
            List of results
        """
        results = []
        total = len(transactions)
        fraud_count = 0
        
        print(f"\nProcessing {total} transactions in real-time...")
        print("-" * 80)
        
        start_time = datetime.now()
        
        for i, transaction in enumerate(transactions):
            result = self.process_transaction(transaction)
            results.append(result)
            
            if result['is_fraud']:
                fraud_count += 1
            
            # Progress indicator
            if (i + 1) % 50 == 0:
                print(f"  ✓ Processed {i + 1}/{total} transactions")
        
        elapsed_time = (datetime.now() - start_time).total_seconds()
        
        print("-" * 80)
        print(f"\n✓ Processing Complete!")
        print(f"  Total Transactions: {total}")
        print(f"  Fraudulent Detected: {fraud_count} ({fraud_count/total*100:.2f}%)")
        print(f"  Processing Time: {elapsed_time:.2f} seconds")
        print(f"  Avg Time per Transaction: {elapsed_time/total*1000:.2f} ms")
        
        return results
    
    def _perform_sql_filtering(self, transaction, customer_profile):
        """
        Perform SQL-based pre-filtering (Theme 5: SQL Query Optimization)

        Uses database queries to identify obvious fraud patterns
        before expensive ML computation
        """
        flags = {
            'threshold_exceeded': False,
            'velocity_anomaly': False,
            'unusual_time': False
        }

        # Check 1: Amount threshold (SQL optimization: indexed queries)
        if transaction['amount'] > customer_profile['avg_transaction'] * 5:
            flags['threshold_exceeded'] = True

        # Check 2: Velocity anomaly (unusual transaction frequency)
        recent_transactions = self.db_manager.get_recent_transactions(
            transaction['customer_id'],
            minutes=60
        )
        if len(recent_transactions) > 10:  # More than 10 in an hour is unusual
            flags['velocity_anomaly'] = True

        # Check 3: Unusual time ('Time' is seconds elapsed since the
        # dataset's first transaction; mod a day's worth of seconds gives
        # a rough time-of-day)
        seconds = transaction.get('Time', 0) or 0
        hour = int((seconds % 86400) // 3600)
        if hour < 6 or hour > 22:  # Outside banking hours
            if customer_profile['unusual_hours_frequency'] < 0.1:
                flags['unusual_time'] = True

        return flags
    
    def _combine_detections(self, sql_flags, ml_fraud, fraud_probability):
        """
        Combine SQL-based and ML detections for final decision (Theme 6)
        
        Uses ensemble approach combining multiple detection methods
        """
        sql_flag_count = sum(1 for v in sql_flags.values() if v)
        
        if sql_flag_count >= 3 or (ml_fraud and sql_flag_count >= 1):
            return 'BLOCK'
        elif sql_flag_count >= 2 or fraud_probability > 0.7:
            return 'REVIEW'
        elif ml_fraud or fraud_probability > 0.5:
            return 'MONITOR'
        else:
            return 'ALLOW'
    
    def _validate_transaction(self, transaction):
        """Validate transaction data"""
        required_fields = ['customer_id', 'amount', 'transaction_id']
        return all(field in transaction for field in required_fields)
    
    def generate_report(self):
        """Generate comprehensive fraud detection report (Theme 7: Business Impact)"""
        print("\n" + "=" * 80)
        print("FRAUD DETECTION REPORT - UGANDA BANKING SECTOR")
        print("=" * 80)
        
        # Get statistics
        stats = self.analytics.get_fraud_statistics()
        
        print("\n[FRAUD STATISTICS]")
        print(f"  Total Transactions Processed: {stats['total_transactions']}")
        print(f"  Fraudulent Transactions Detected: {stats['fraud_count']}")
        print(f"  Fraud Detection Rate: {stats['fraud_rate']:.2%}")
        print(f"  Average Fraud Score: {stats['avg_fraud_score']:.2%}")
        
        print("\n[DETECTION BREAKDOWN]")
        print(f"  Blocked Transactions: {stats['blocked']}")
        print(f"  Under Review: {stats['review']}")
        print(f"  Being Monitored: {stats['monitor']}")
        print(f"  Allowed: {stats['allowed']}")
        
        print("\n[FINANCIAL IMPACT]")
        print(f"  Total Transaction Amount: {stats['total_amount']:,.0f} UGX")
        print(f"  Fraudulent Amount Detected: {stats['fraud_amount']:,.0f} UGX")
        print(f"  Potential Loss Prevention: {stats['fraud_amount']:,.0f} UGX")
        print(f"  Prevention Rate: {stats['prevention_rate']:.2%}")
        
        print("\n[SYSTEM PERFORMANCE]")
        print(f"  Average Processing Time: {stats['avg_processing_time']:.2f} ms")
        print(f"  System Uptime: {stats['uptime']:.1f}%")
        print(f"  False Positive Rate: {stats['false_positive_rate']:.2%}")
        
        print("\n[TOP FRAUD PATTERNS]")
        patterns = self.analytics.get_fraud_patterns()
        for i, pattern in enumerate(patterns[:5], 1):
            print(f"  {i}. {pattern['pattern']}: {pattern['count']} cases")
        
        print("\n" + "=" * 80)
    
    def export_results(self, filename='fraud_detection_results.json'):
        """Export detection results to JSON"""
        data = self.db_manager.get_all_transactions()
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        print(f"\n✓ Results exported to {filename}")
        return filename


def main():
    """Main execution function"""
    
    try:
        # Create and initialize system
        system = FraudDetectionSystem()
        
        # Setup the system
        sample_transactions = system.setup_system()
        
        # Process transactions in real-time
        print("\n" + "=" * 80)
        print("REAL-TIME TRANSACTION PROCESSING")
        print("=" * 80)
        
        results = system.batch_process_transactions(sample_transactions)
        
        # Generate report
        system.generate_report()
        
        # Export results
        system.export_results('uganda_fraud_detection_results.json')
        
        print("\n" + "=" * 80)
        print("✓ FRAUD DETECTION SYSTEM RUN COMPLETED SUCCESSFULLY")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
