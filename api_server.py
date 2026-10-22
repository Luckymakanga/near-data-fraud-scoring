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

import os
import time
import ipaddress
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
from datetime import datetime, timedelta
from functools import wraps
import hmac
import uuid
import jwt
import logging
from werkzeug.security import check_password_hash

from results_summary import build_summary
from validation import ID_RULE, valid_id, validate_transaction

# The dashboard re-reads these three routes while it is open (every 30 s, about 120 an hour each
# per tab); the limit leaves room for several tabs and manual refreshes without locking it out.
DASHBOARD_REFRESH_LIMIT = "600 per hour"

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
        self.app.config['SECRET_KEY'] = self._load_secret_key(debug)
        CORS(self.app)

        self.system = fraud_detection_system
        self.port = port
        self.debug = debug
        self._load_admin_credentials()

        # Rate limiting, counted per visitor (see _client_address)
        self.client_ip_header = self._client_ip_header_setting()
        self.limiter = Limiter(
            app=self.app,
            key_func=self._client_address,
            default_limits=["200 per day", "50 per hour"]
        )

        # Setup routes
        self._setup_routes()

        logger.info("Fraud Detection API initialized")

    @staticmethod
    def _client_ip_header_setting():
        """Name of the request header that carries the real visitor's address, or None.

        Behind a hosting proxy every request reaches the service from the proxy's own
        address, so counting limits by that address makes all visitors share one limit.
        The host's edge puts the visitor's address in a header, and the service may read
        it only where the edge is known to set it, because anywhere else a caller could
        write any value into the header and dodge the limits. It is therefore off by
        default. Render sets RENDER=true, and its edge is Cloudflare, which sets
        CF-Connecting-IP; CLIENT_IP_HEADER names another header, or empty to turn it off."""
        configured = os.environ.get('CLIENT_IP_HEADER')
        if configured is not None:
            return configured.strip() or None
        if os.environ.get('RENDER', '').lower() == 'true':
            return 'CF-Connecting-IP'
        return None

    def _client_address(self):
        """The address a request's limits are counted against"""
        if self.client_ip_header:
            value = request.headers.get(self.client_ip_header, '').strip()
            try:
                return str(ipaddress.ip_address(value))
            except ValueError:
                pass  # missing or not an address: fall back to the connecting address
        return get_remote_address()

    @staticmethod
    def _load_secret_key(debug):
        """The token-signing key comes from SECRET_KEY. There is no built-in default
        outside debug mode: a key written in the source code would let anyone who
        has read it forge tokens."""
        secret_key = os.environ.get('SECRET_KEY')
        if secret_key:
            return secret_key
        if debug:
            logger.warning("SECRET_KEY is not set; using a development-only key (debug mode)")
            return 'development-only-key-not-for-production'
        raise RuntimeError(
            "SECRET_KEY is not set. Set it in the environment or in .env, for example: "
            "python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    def _load_admin_credentials(self):
        """Admin login from the environment: ADMIN_USERNAME (default 'admin') and either
        ADMIN_PASSWORD_HASH (a Werkzeug password hash, preferred) or ADMIN_PASSWORD.
        If neither password variable is set, the public demo password is used and a
        warning is logged."""
        self.admin_username = os.environ.get('ADMIN_USERNAME', 'admin')
        self.admin_password_hash = os.environ.get('ADMIN_PASSWORD_HASH')
        self.admin_password = os.environ.get('ADMIN_PASSWORD')
        if not self.admin_password_hash and not self.admin_password:
            self.admin_password = 'admin'
            logger.warning(
                "ADMIN_PASSWORD / ADMIN_PASSWORD_HASH are not set: the public demo password "
                "is in use. Set one of them for any real deployment."
            )

    def _credentials_ok(self, username, password):
        """Constant-time comparison of the supplied login with the configured one"""
        user_ok = hmac.compare_digest(username.encode('utf-8'), self.admin_username.encode('utf-8'))
        if self.admin_password_hash:
            password_ok = check_password_hash(self.admin_password_hash, password)
        else:
            password_ok = hmac.compare_digest(password.encode('utf-8'), self.admin_password.encode('utf-8'))
        return user_ok and password_ok

    @staticmethod
    def _log_failure(context, exc):
        """Log a failure with a short reference the caller can quote; returns the reference"""
        error_id = uuid.uuid4().hex[:8]
        logger.error("[%s] %s failed: %s", error_id, context, exc, exc_info=True)
        return error_id

    @classmethod
    def _server_error(cls, context, exc):
        """A generic 500. The detail goes to the log with a short reference the
        caller can quote, never to the caller (it could reveal internals)."""
        return jsonify({'error': 'Internal server error', 'error_id': cls._log_failure(context, exc)}), 500

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
        @self.limiter.limit("10 per minute")
        def login():
            """Login and get JWT token"""
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({'error': 'Request body must be JSON'}), 400

            username = data.get('username')
            password = data.get('password')
            if not isinstance(username, str) or not isinstance(password, str):
                return jsonify({'error': 'username and password must be text'}), 400

            if self._credentials_ok(username, password):
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
                transaction_data = request.get_json(silent=True)

                # Validate transaction (ids are restricted to a plain character set)
                problem = validate_transaction(transaction_data)
                if problem:
                    return jsonify({'error': problem}), 400

                # Process transaction
                result = self.system.process_transaction(transaction_data, explain=True)

                return jsonify({
                    'status': 'success',
                    'result': result,
                    'timestamp': datetime.now().isoformat()
                }), 200

            except Exception as e:
                logger.error(f"Error analyzing transaction: {str(e)}")
                return self._server_error('analyze_transaction', e)

        # Batch analysis endpoint
        @self.app.route('/api/transactions/batch-analyze', methods=['POST'])
        @self.limiter.limit("200 per hour")
        @self._token_required
        def batch_analyze():
            """
            Analyze multiple transactions synchronously and return every
            result in the response (e.g. for a bulk CSV upload). Rows
            missing a required field are skipped and reported separately
            rather than failing the whole batch.
            """
            try:
                data = request.get_json(silent=True)
                transactions = data.get('transactions', []) if isinstance(data, dict) else []

                if not isinstance(transactions, list) or not transactions:
                    return jsonify({'error': 'No transactions provided'}), 400

                if len(transactions) > 500:
                    return jsonify({'error': 'Maximum 500 transactions per request'}), 400

                results = []
                errors = []
                started = time.monotonic()

                # The rows of one batch share their reads of each customer's profile and
                # hourly count, which would otherwise be a round trip per row to a database
                # that may be far away. Systems without that (test stand-ins) score row by row.
                start_batch = getattr(self.system, 'start_batch', None)
                batch = start_batch() if start_batch else None

                consecutive_failures = 0
                stopped_early = False
                for i, txn in enumerate(transactions):
                    problem = validate_transaction(txn)
                    if problem:
                        errors.append({'index': i, 'error': problem})
                        continue
                    try:
                        result = (self.system.process_transaction(txn, batch=batch) if batch
                                  else self.system.process_transaction(txn))
                    except Exception as e:
                        # one row failing does not cancel the rows already stored; three in a
                        # row means something systemic (such as the database), so stop
                        error_id = self._log_failure('batch_analyze row', e)
                        errors.append({'index': i, 'error': f'Could not be scored (reference {error_id})'})
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            stopped_early = True
                            break
                        continue
                    consecutive_failures = 0
                    results.append(result)

                fraud_count = sum(1 for r in results if r.get('is_fraud'))
                elapsed = time.monotonic() - started

                return jsonify({
                    'status': 'success',
                    'results': results,
                    'errors': errors,
                    'summary': {
                        'total': len(results),
                        'fraud_count': fraud_count,
                        'skipped': len(errors),
                        'stopped_early': stopped_early,
                        'elapsed_seconds': round(elapsed, 2),
                    },
                    'timestamp': datetime.now().isoformat()
                }), 200

            except Exception as e:
                logger.error(f"Error in batch analysis: {str(e)}")
                return self._server_error('batch_analyze', e)

        # Recent transactions (for admin/dashboard views)
        @self.app.route('/api/transactions/recent', methods=['GET'])
        @self.limiter.limit(DASHBOARD_REFRESH_LIMIT)
        @self._token_required
        def get_recent_transactions():
            """Get the most recent transactions, newest first. Optional ?decision=BLOCK|REVIEW|MONITOR|ALLOW filters to that outcome."""
            try:
                limit = request.args.get('limit', default=50, type=int)
                limit = max(1, min(limit, 200))

                decision = request.args.get('decision', default=None, type=str)
                valid_decisions = {'BLOCK', 'REVIEW', 'MONITOR', 'ALLOW'}
                if decision and decision not in valid_decisions:
                    return jsonify({'error': f"Invalid decision filter. Must be one of {sorted(valid_decisions)}"}), 400

                transactions = self.system.db_manager.get_latest_transactions(limit, decision=decision)

                return jsonify({
                    'status': 'success',
                    'transactions': transactions,
                    'count': len(transactions),
                    'timestamp': datetime.now().isoformat()
                }), 200

            except Exception as e:
                logger.error(f"Error fetching recent transactions: {str(e)}")
                return self._server_error('get_recent_transactions', e)

        # Sample a real transaction from the training dataset (for the
        # Analyze form - its predictive features are anonymized PCA
        # components, so there's nothing meaningful an admin could type by hand)
        @self.app.route('/api/transactions/sample', methods=['GET'])
        @self.limiter.limit("200 per hour")
        @self._token_required
        def get_sample_transaction():
            """Get one random real transaction from the training dataset, not yet analyzed"""
            try:
                sample = self.system.transaction_processor.generate_sample_transactions(n=1)[0]
                true_label = 'FRAUD' if sample.pop('is_fraud_label') else 'NORMAL'
                sample['timestamp'] = sample['timestamp'].isoformat()

                return jsonify({
                    'status': 'success',
                    'transaction': sample,
                    'true_label': true_label
                }), 200

            except Exception as e:
                logger.error(f"Error sampling transaction: {str(e)}")
                return self._server_error('get_sample_transaction', e)

        # Statistics endpoints
        @self.app.route('/api/statistics/fraud', methods=['GET'])
        @self.limiter.limit(DASHBOARD_REFRESH_LIMIT)
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
                return self._server_error('get_fraud_stats', e)

        # Fraud patterns endpoint
        @self.app.route('/api/statistics/patterns', methods=['GET'])
        @self.limiter.limit(DASHBOARD_REFRESH_LIMIT)
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
                return self._server_error('get_patterns', e)

        # Customer risk profile
        @self.app.route('/api/customers/<customer_id>/risk-profile', methods=['GET'])
        @self.limiter.limit("200 per hour")
        @self._token_required
        def get_customer_risk(customer_id):
            """Get customer risk profile"""
            if not valid_id(customer_id):
                return jsonify({'error': f'customer_id {ID_RULE}'}), 400
            try:
                profile = self.system.db_manager.get_customer_profile(customer_id)

                return jsonify({
                    'status': 'success',
                    'customer_id': customer_id,
                    'profile': profile,
                    'timestamp': datetime.now().isoformat()
                }), 200

            except Exception as e:
                return self._server_error('get_customer_risk', e)

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
                return self._server_error('get_roi', e)

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
                return self._server_error('executive_summary', e)

        # The study's measured results, for the dashboard's research page
        @self.app.route('/api/research/results', methods=['GET'])
        @self.limiter.limit("60 per hour")
        @self._token_required
        def research_results():
            """Condensed results of the architecture benchmarks (read from results/)"""
            try:
                return jsonify({
                    'status': 'success',
                    'results': build_summary(),
                    'timestamp': datetime.now().isoformat()
                }), 200
            except Exception as e:
                return self._server_error('research_results', e)

        # Health check
        @self.app.route('/api/health', methods=['GET'])
        @self.limiter.exempt
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

    def run(self):
        """Start the API server using Flask's own dev server (local use only)"""
        logger.info(f"Starting Fraud Detection API on port {self.port}")
        self.app.run(host='0.0.0.0', port=self.port, debug=self.debug)


# Module-level system + app setup, so a production WSGI server (gunicorn,
# per the Procfile/render.yaml) can import this module and serve `app`
# directly without ever calling .run(). This also means training happens
# once, here, at import time, regardless of how the module is loaded.
from fraud_detection_system import FraudDetectionSystem

system = FraudDetectionSystem()
system.setup_system()

_debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
_port = int(os.environ.get('PORT', 5000))

api = FraudDetectionAPI(system, port=_port, debug=_debug)
app = api.app

if __name__ == '__main__':
    api.run()
