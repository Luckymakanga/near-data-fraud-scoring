"""
ADVANCED FRAUD DETECTION SYSTEM - API SERVER
Complex Enterprise-Grade Implementation

Features:
- RESTful API endpoints
- Real-time WebSocket support
- JWT authentication
- Advanced logging and monitoring
- Multi-threading support
- Request queuing
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    # Windows consoles default to a legacy codepage (e.g. cp1252) that can't
    # encode the checkmark/emoji characters this system prints.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import threading
from datetime import datetime, timedelta
from functools import wraps
import jwt
import logging
from queue import Queue
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class FraudDetectionAPI:
    """
    Advanced API server for fraud detection system
    Provides RESTful endpoints for fraud detection and monitoring
    """
    
    def __init__(self, fraud_detection_system, port=5000, debug=False):
        """Initialize API server"""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'uganda-fraud-detection-secret-key'
        CORS(self.app)
        
        self.system = fraud_detection_system
        self.port = port
        self.debug = debug
        
        # Rate limiting
        self.limiter = Limiter(
            app=self.app,
            key_func=get_remote_address,
            default_limits=["200 per day", "50 per hour"]
        )
        
        # Request queue for async processing
        self.request_queue = Queue(maxsize=1000)
        
        # Worker thread for processing queued requests
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()
        
        # Setup routes
        self._setup_routes()
        
        logger.info("Fraud Detection API initialized")
    
    def _token_required(self, f):
        """Decorator for JWT token authentication"""
        @wraps(f)
        def decorated(*args, **kwargs):
            token = request.headers.get('Authorization', '').replace('Bearer ', '')
            
            if not token:
                return jsonify({'error': 'Missing authentication token'}), 401
            
            try:
                data = jwt.decode(token, self.app.config['SECRET_KEY'], algorithms=['HS256'])
            except jwt.ExpiredSignatureError:
                return jsonify({'error': 'Token expired'}), 401
            except jwt.InvalidTokenError:
                return jsonify({'error': 'Invalid token'}), 401
            
            return f(*args, **kwargs)
        
        return decorated
    
    def _setup_routes(self):
        """Setup all API routes"""
        
        # Authentication endpoints
        @self.app.route('/api/auth/login', methods=['POST'])
        def login():
            """Login and get JWT token"""
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
            
            # Simple authentication (in production, use database)
            if username == 'admin' and password == 'admin':
                token = jwt.encode({
                    'username': username,
                    'exp': datetime.utcnow() + timedelta(hours=24)
                }, self.app.config['SECRET_KEY'], algorithm='HS256')
                
                return jsonify({'token': token, 'message': 'Login successful'}), 200
            
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Transaction detection endpoints
        @self.app.route('/api/transactions/analyze', methods=['POST'])
        @self.limiter.limit("100 per hour")
        @self._token_required
        def analyze_transaction():
            """Analyze single transaction for fraud"""
            try:
                transaction_data = request.get_json()
                
                # Validate transaction
                required_fields = ['customer_id', 'amount', 'transaction_id', 'merchant_category']
                if not all(f in transaction_data for f in required_fields):
                    return jsonify({'error': 'Missing required fields'}), 400
                
                # Process transaction
                result = self.system.process_transaction(transaction_data)
                
                return jsonify({
                    'status': 'success',
                    'result': result,
                    'timestamp': datetime.now().isoformat()
                }), 200
                
            except Exception as e:
                logger.error(f"Error analyzing transaction: {str(e)}")
                return jsonify({'error': str(e)}), 500
        
        # Batch analysis endpoint
        @self.app.route('/api/transactions/batch-analyze', methods=['POST'])
        @self.limiter.limit("20 per hour")
        @self._token_required
        def batch_analyze():
            """Analyze multiple transactions"""
            try:
                data = request.get_json()
                transactions = data.get('transactions', [])
                
                if not transactions:
                    return jsonify({'error': 'No transactions provided'}), 400
                
                if len(transactions) > 1000:
                    return jsonify({'error': 'Maximum 1000 transactions per request'}), 400
                
                # Queue for async processing
                job_id = f'JOB{int(time.time())}'
                
                self.request_queue.put({
                    'job_id': job_id,
                    'transactions': transactions,
                    'timestamp': datetime.now()
                })
                
                return jsonify({
                    'status': 'queued',
                    'job_id': job_id,
                    'message': f'Processing {len(transactions)} transactions'
                }), 202
                
            except Exception as e:
                logger.error(f"Error in batch analysis: {str(e)}")
                return jsonify({'error': str(e)}), 500

        # Recent transactions (for admin/dashboard views)
        @self.app.route('/api/transactions/recent', methods=['GET'])
        @self.limiter.limit("200 per hour")
        @self._token_required
        def get_recent_transactions():
            """Get the most recent transactions, newest first"""
            try:
                limit = request.args.get('limit', default=50, type=int)
                limit = max(1, min(limit, 200))

                transactions = self.system.db_manager.get_latest_transactions(limit)

                return jsonify({
                    'status': 'success',
                    'transactions': transactions,
                    'count': len(transactions),
                    'timestamp': datetime.now().isoformat()
                }), 200

            except Exception as e:
                logger.error(f"Error fetching recent transactions: {str(e)}")
                return jsonify({'error': str(e)}), 500

        # Statistics endpoints
        @self.app.route('/api/statistics/fraud', methods=['GET'])
        @self.limiter.limit("200 per hour")
        @self._token_required
        def get_fraud_stats():
            """Get current fraud statistics"""
            try:
                stats = self.system.analytics.get_fraud_statistics()
                
                return jsonify({
                    'status': 'success',
                    'statistics': stats,
                    'timestamp': datetime.now().isoformat()
                }), 200
                
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # Fraud patterns endpoint
        @self.app.route('/api/statistics/patterns', methods=['GET'])
        @self.limiter.limit("100 per hour")
        @self._token_required
        def get_patterns():
            """Get fraud patterns"""
            try:
                patterns = self.system.analytics.get_fraud_patterns()
                
                return jsonify({
                    'status': 'success',
                    'patterns': patterns,
                    'timestamp': datetime.now().isoformat()
                }), 200
                
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # Customer risk profile
        @self.app.route('/api/customers/<customer_id>/risk-profile', methods=['GET'])
        @self.limiter.limit("200 per hour")
        @self._token_required
        def get_customer_risk(customer_id):
            """Get customer risk profile"""
            try:
                profile = self.system.db_manager.get_customer_profile(customer_id)
                
                return jsonify({
                    'status': 'success',
                    'customer_id': customer_id,
                    'profile': profile,
                    'timestamp': datetime.now().isoformat()
                }), 200
                
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # ROI metrics
        @self.app.route('/api/metrics/roi', methods=['GET'])
        @self.limiter.limit("50 per hour")
        @self._token_required
        def get_roi():
            """Get ROI metrics"""
            try:
                roi = self.system.analytics.get_roi_metrics()
                
                return jsonify({
                    'status': 'success',
                    'roi_metrics': roi,
                    'timestamp': datetime.now().isoformat()
                }), 200
                
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # Executive summary
        @self.app.route('/api/reports/executive-summary', methods=['GET'])
        @self.limiter.limit("50 per hour")
        @self._token_required
        def executive_summary():
            """Get executive summary"""
            try:
                summary = self.system.analytics.generate_executive_summary()
                
                return jsonify({
                    'status': 'success',
                    'summary': summary,
                    'timestamp': datetime.now().isoformat()
                }), 200
                
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # Health check
        @self.app.route('/api/health', methods=['GET'])
        def health_check():
            """API health check"""
            return jsonify({
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'service': 'Fraud Detection System',
                'version': '2.0'
            }), 200
        
        # Error handlers
        @self.app.errorhandler(404)
        def not_found(error):
            return jsonify({'error': 'Endpoint not found'}), 404
        
        @self.app.errorhandler(500)
        def internal_error(error):
            logger.error(f"Internal server error: {error}")
            return jsonify({'error': 'Internal server error'}), 500
    
    def _process_queue(self):
        """Process queued requests in background"""
        logger.info("Queue processor started")
        
        while True:
            try:
                if not self.request_queue.empty():
                    job = self.request_queue.get(timeout=1)
                    
                    logger.info(f"Processing job {job['job_id']} with {len(job['transactions'])} transactions")
                    
                    # Process batch
                    results = self.system.batch_process_transactions(job['transactions'])
                    
                    logger.info(f"Job {job['job_id']} completed")
                    
                else:
                    time.sleep(0.5)
                    
            except Exception as e:
                logger.error(f"Error processing queue: {str(e)}")
    
    def run(self):
        """Start the API server"""
        logger.info(f"Starting Fraud Detection API on port {self.port}")
        self.app.run(host='0.0.0.0', port=self.port, debug=self.debug)


# Example usage
if __name__ == '__main__':
    from fraud_detection_system import FraudDetectionSystem
    
    # Initialize fraud detection system
    system = FraudDetectionSystem()
    system.setup_system()
    
    # Initialize and run API
    api = FraudDetectionAPI(system, port=5000, debug=True)
    api.run()
