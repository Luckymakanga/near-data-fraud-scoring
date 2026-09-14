"""
ADVANCED REAL-TIME STREAMING MODULE
Theme 2: Real-Time Fraud Detection Systems

Features:
- Continuous stream processing
- Sliding window analysis
- Real-time feature computation
- Concept drift detection
- Adaptive thresholding
- Stream statistics tracking
"""

import numpy as np
from collections import deque
from datetime import datetime, timedelta
import threading
from queue import Queue
import statistics

class StreamProcessor:
    """
    Advanced real-time stream processor for continuous transaction analysis
    Theme 2: Real-Time Detection
    """
    
    def __init__(self, window_size=300):  # 300-second window
        """Initialize stream processor"""
        self.window_size = window_size
        self.transaction_buffer = deque(maxlen=window_size)
        self.fraud_buffer = deque(maxlen=window_size)
        self.alert_queue = Queue()
        
        # Statistics tracking
        self.stream_stats = {
            'transactions_processed': 0,
            'frauds_detected': 0,
            'avg_amount': 0,
            'avg_fraud_score': 0,
            'throughput_tps': 0  # Transactions per second
        }
        
        # Concept drift detection
        self.historical_fraud_rate = 0.03
        self.current_fraud_rate = 0.03
        self.concept_drift_threshold = 0.02  # 2% change
        
        # Adaptive threshold
        self.base_threshold = 0.5
        self.adaptive_threshold = 0.5
        
        # Real-time metrics
        self.start_time = datetime.now()
        self.processing_times = deque(maxlen=100)
    
    def add_transaction(self, transaction_result):
        """
        Add transaction result to stream
        Updates real-time statistics
        """
        self.transaction_buffer.append(transaction_result)
        
        if transaction_result.get('is_fraud'):
            self.fraud_buffer.append(transaction_result)
        
        # Update stream statistics
        self._update_stream_stats(transaction_result)
        
        # Check for concept drift (Theme 6)
        self._detect_concept_drift()
        
        # Update adaptive threshold
        self._update_adaptive_threshold()
    
    def _update_stream_stats(self, transaction):
        """Update stream statistics in real-time"""
        self.stream_stats['transactions_processed'] += 1
        
        if transaction.get('is_fraud'):
            self.stream_stats['frauds_detected'] += 1
        
        # Update rolling averages
        if self.transaction_buffer:
            amounts = [t['amount'] for t in self.transaction_buffer]
            fraud_scores = [t['fraud_score'] for t in self.transaction_buffer]
            
            self.stream_stats['avg_amount'] = statistics.mean(amounts)
            self.stream_stats['avg_fraud_score'] = statistics.mean(fraud_scores)
            
            # Calculate throughput (transactions per second)
            elapsed = (datetime.now() - self.start_time).total_seconds()
            if elapsed > 0:
                self.stream_stats['throughput_tps'] = self.stream_stats['transactions_processed'] / elapsed
    
    def _detect_concept_drift(self):
        """
        Detect concept drift in fraud patterns
        Theme 6: Handling Evolving Threats
        
        If fraud patterns change significantly, model may need retraining
        """
        if len(self.transaction_buffer) < 100:
            return
        
        # Calculate current fraud rate
        current_fraud_count = len(self.fraud_buffer)
        total_transactions = len(self.transaction_buffer)
        
        self.current_fraud_rate = current_fraud_count / max(total_transactions, 1)
        
        # Calculate drift
        drift = abs(self.current_fraud_rate - self.historical_fraud_rate)
        
        if drift > self.concept_drift_threshold:
            print(f"\n⚠️ CONCEPT DRIFT DETECTED!")
            print(f"   Historical fraud rate: {self.historical_fraud_rate:.2%}")
            print(f"   Current fraud rate: {self.current_fraud_rate:.2%}")
            print(f"   Drift: {drift:.2%}")
            print(f"   ⚠️ Model retraining recommended!")
            
            # Alert about concept drift
            self.alert_queue.put({
                'type': 'CONCEPT_DRIFT',
                'severity': 'HIGH',
                'message': f'Concept drift detected: {drift:.2%}',
                'timestamp': datetime.now().isoformat()
            })
            
            # Update historical rate
            self.historical_fraud_rate = self.current_fraud_rate
    
    def _update_adaptive_threshold(self):
        """
        Update fraud detection threshold adaptively
        Theme 6: Handling Challenges
        
        Adjusts threshold based on current fraud patterns
        """
        if len(self.transaction_buffer) < 50:
            return
        
        fraud_scores = [t['fraud_score'] for t in self.transaction_buffer]
        
        # Calculate statistics
        mean_score = statistics.mean(fraud_scores)
        stdev_score = statistics.stdev(fraud_scores) if len(fraud_scores) > 1 else 0.1
        
        # Adaptive threshold: mean + 0.5 std dev
        new_threshold = min(max(mean_score + 0.5 * stdev_score, 0.3), 0.7)
        
        self.adaptive_threshold = new_threshold
    
    def get_sliding_window_stats(self):
        """Get statistics for the sliding window"""
        if not self.transaction_buffer:
            return {}
        
        transactions = list(self.transaction_buffer)
        fraud_transactions = list(self.fraud_buffer)
        
        amounts = [t['amount'] for t in transactions]
        fraud_scores = [t['fraud_score'] for t in transactions]
        
        return {
            'window_size': len(transactions),
            'fraud_count': len(fraud_transactions),
            'fraud_rate': len(fraud_transactions) / max(len(transactions), 1),
            'avg_amount': statistics.mean(amounts),
            'max_amount': max(amounts),
            'min_amount': min(amounts),
            'avg_fraud_score': statistics.mean(fraud_scores),
            'max_fraud_score': max(fraud_scores),
            'std_dev_fraud_score': statistics.stdev(fraud_scores) if len(fraud_scores) > 1 else 0,
            'adaptive_threshold': self.adaptive_threshold
        }
    
    def get_stream_performance(self):
        """Get real-time stream performance metrics"""
        if not self.processing_times:
            return {}
        
        return {
            'total_transactions': self.stream_stats['transactions_processed'],
            'total_frauds': self.stream_stats['frauds_detected'],
            'fraud_detection_rate': (self.stream_stats['frauds_detected'] / 
                                    max(self.stream_stats['transactions_processed'], 1)),
            'throughput_tps': round(self.stream_stats['throughput_tps'], 2),
            'avg_processing_time_ms': round(statistics.mean(self.processing_times) * 1000, 2),
            'median_processing_time_ms': round(statistics.median(self.processing_times) * 1000, 2),
            'p95_processing_time_ms': round(np.percentile(self.processing_times, 95) * 1000, 2),
            'p99_processing_time_ms': round(np.percentile(self.processing_times, 99) * 1000, 2),
            'uptime_seconds': (datetime.now() - self.start_time).total_seconds(),
            'current_concept_drift': abs(self.current_fraud_rate - self.historical_fraud_rate)
        }
    
    def add_processing_time(self, processing_time):
        """Track processing time for latency monitoring"""
        self.processing_times.append(processing_time)


class AnomalyDetector:
    """
    Advanced anomaly detection using statistical methods
    Theme 4: Data Mining and Anomaly Detection
    """
    
    def __init__(self, window_size=100):
        """Initialize anomaly detector"""
        self.window_size = window_size
        self.transaction_history = deque(maxlen=window_size)
        self.anomaly_scores = deque(maxlen=window_size)
        
        # Statistical baselines
        self.amount_baseline = None
        self.frequency_baseline = None
        self.merchant_baseline = None
    
    def compute_anomaly_score(self, transaction, customer_profile):
        """
        Compute comprehensive anomaly score
        Theme 4: Anomaly Detection
        
        Returns:
            Anomaly score (0-1, higher = more anomalous)
        """
        anomaly_components = []
        
        # 1. Statistical anomaly in amount
        amount_anomaly = self._compute_amount_anomaly(transaction, customer_profile)
        anomaly_components.append(amount_anomaly)
        
        # 2. Frequency anomaly
        frequency_anomaly = self._compute_frequency_anomaly(transaction)
        anomaly_components.append(frequency_anomaly)
        
        # 3. Behavioral anomaly
        behavioral_anomaly = self._compute_behavioral_anomaly(transaction, customer_profile)
        anomaly_components.append(behavioral_anomaly)
        
        # 4. Statistical outlier test (Isolation Score)
        isolation_score = self._compute_isolation_score(transaction)
        anomaly_components.append(isolation_score)
        
        # Combine anomaly scores (weighted)
        weights = [0.3, 0.2, 0.3, 0.2]
        combined_score = sum(s * w for s, w in zip(anomaly_components, weights))
        
        # Store for tracking
        self.anomaly_scores.append(combined_score)
        self.transaction_history.append(transaction)
        
        return min(max(combined_score, 0), 1)
    
    def _compute_amount_anomaly(self, transaction, customer_profile):
        """Compute amount anomaly using MAD (Median Absolute Deviation)"""
        amount = transaction['amount']
        
        if not self.transaction_history:
            return 0.5
        
        amounts = [t['amount'] for t in self.transaction_history]
        median = statistics.median(amounts)
        mad = statistics.median([abs(x - median) for x in amounts])
        
        if mad == 0:
            return 1.0 if abs(amount - median) > median * 0.1 else 0.0
        
        # Modified Z-score
        modified_zscore = 0.6745 * (amount - median) / max(mad, 1)
        anomaly = min(abs(modified_zscore) / 3.5, 1.0)  # Normalize
        
        return anomaly
    
    def _compute_frequency_anomaly(self, transaction):
        """Detect transaction frequency anomalies"""
        if len(self.transaction_history) < 10:
            return 0.3
        
        # Check if rapid successive transactions
        recent_transactions = list(self.transaction_history)[-5:]
        
        if len(recent_transactions) >= 5:
            # 5 transactions in last 100 entries is high frequency
            return min(len(recent_transactions) / 10, 1.0)
        
        return 0.2
    
    def _compute_behavioral_anomaly(self, transaction, customer_profile):
        """Detect behavioral deviations"""
        anomaly = 0.0
        
        # Merchant anomaly
        usual_merchants = customer_profile.get('usual_merchants', [])
        if transaction.get('merchant_category') not in usual_merchants:
            anomaly += 0.3
        
        # Location anomaly
        usual_location = customer_profile.get('last_location', 'Kampala')
        if transaction.get('location') != usual_location:
            anomaly += 0.2
        
        # Time anomaly
        hour = transaction.get('hour', 12)
        if hour < 6 or hour > 22:
            if customer_profile.get('unusual_hours_frequency', 0.1) < 0.2:
                anomaly += 0.2
        
        return min(anomaly, 1.0)
    
    def _compute_isolation_score(self, transaction):
        """Compute isolation score (how isolated in feature space)"""
        if len(self.transaction_history) < 20:
            return 0.5
        
        # Use amount and frequency as primary features
        amount = transaction['amount']
        amounts = [t['amount'] for t in list(self.transaction_history)[-20:]]
        
        # Compute distance to nearest neighbors
        distances = sorted([abs(amount - a) for a in amounts])
        
        # Average distance to 3 nearest neighbors
        nearest_distance = sum(distances[:3]) / 3 if len(distances) >= 3 else sum(distances) / len(distances)
        
        # Normalize
        max_distance = max(amounts) - min(amounts) if len(amounts) > 1 else 1
        isolation = nearest_distance / max(max_distance, 1) if max_distance > 0 else 0.5
        
        return min(isolation, 1.0)
