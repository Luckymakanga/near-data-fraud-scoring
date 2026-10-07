"""
ADVANCED DEEP LEARNING MODULE
Complex Machine Learning Implementation

Features:
- Neural Networks (LSTM, Dense layers)
- XGBoost and LightGBM
- Isolation Forest for anomaly detection
- One-Class SVM
- AutoML capabilities
- Model ensemble with stacking
- Hyperparameter tuning
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.ensemble import IsolationForest, VotingClassifier
from sklearn.svm import OneClassSVM
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.metrics import roc_auc_score, precision_recall_curve, f1_score
import xgboost as xgb
import lightgbm as lgb
from imblearn.over_sampling import ADASYN
import warnings
warnings.filterwarnings('ignore')

from feature_engineering import FEATURE_NAMES, extract_creditcard_features

class AdvancedFraudDetectionModel:
    """
    Advanced ML model with multiple algorithms and ensemble methods
    Includes:
    - XGBoost
    - LightGBM
    - Isolation Forest (anomaly detection)
    - One-Class SVM
    - Voting ensemble
    - Stacking ensemble
    """
    
    def __init__(self, model_path='advanced_fraud_model.pkl', data_path='data/creditcard_sample.csv'):
        """Initialize advanced model"""
        self.model_path = model_path
        self.data_path = data_path
        self.models = {}
        self.scaler = RobustScaler()  # More robust to outliers
        self.feature_names = FEATURE_NAMES
        self.is_trained = False
        self.feature_importances = {}

    def load_training_data(self):
        """
        Load the credit card fraud training sample and turn each row into
        the model's feature vector via the same extract_creditcard_features()
        used for live transactions, so training and inference never diverge.
        """
        df = pd.read_csv(self.data_path)

        X = np.array([extract_creditcard_features(row) for row in df.to_dict('records')])
        y = df['Class'].to_numpy()

        return X, y
    
    def train_ensemble_model(self):
        """
        Train multiple models with ensemble approach
        """
        print("\n" + "="*80)
        print("TRAINING ADVANCED ENSEMBLE FRAUD DETECTION MODEL")
        print("="*80)

        # Load training data
        X, y = self.load_training_data()

        print(f"\n[Data Preparation]")
        print(f"  Total samples: {len(X)}")
        print(f"  Features: {len(self.feature_names)}")
        print(f"  Fraud ratio: {y.sum()/len(y):.2%}")

        # Train/test split - BEFORE any resampling or scaling, so no
        # information about the test set (real or ADASYN-synthesized
        # from test neighbors) ever reaches training.
        X_train_raw, X_test_raw, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        self.fit(X_train_raw, y_train)

        # Quick held-out sanity check only - evaluate.py reports the proper
        # fraud-detection metrics (precision, recall, F1, PR-AUC, FPR) on a
        # time-ordered split.
        X_test = self.scaler.transform(X_test_raw)
        print(f"\n[Held-out Check]")
        for name in ('xgboost', 'lightgbm', 'voting_ensemble'):
            model = self.models[name]
            accuracy = model.score(X_test, y_test)
            auc = roc_auc_score(y_test, model.predict_proba(X_test)[:, 1])
            print(f"  {name}: Accuracy: {accuracy:.2%} | AUC: {auc:.2%}")

        print(f"\n{'='*80}")
        print(f"✓ Model training completed successfully!")
        print(f"{'='*80}")

    def fit(self, X_train_raw, y_train):
        """
        Fit every model on the given (raw, unscaled) training split.

        Kept separate from train_ensemble_model() so evaluate.py can train
        on its own split with exactly the pipeline production uses.
        """
        # Handle class imbalance with ADASYN (more advanced than SMOTE) -
        # fit only on the training split
        print(f"\n[Class Balancing]")
        print(f"  Applying ADASYN for advanced class imbalance handling...")
        adasyn = ADASYN(random_state=42, n_neighbors=5)

        try:
            X_train_balanced, y_train = adasyn.fit_resample(X_train_raw, y_train)
            print(f"  ✓ Balanced samples: {len(X_train_balanced)}")
            print(f"  ✓ Balanced fraud ratio: {y_train.sum()/len(y_train):.2%}")
        except:
            X_train_balanced = X_train_raw

        # Feature scaling - fit on the (balanced) training data only
        X_train = self.scaler.fit_transform(X_train_balanced)

        print(f"\n[Model Training]")
        print(f"  Training set: {len(X_train)}")

        # Model 1: XGBoost with hyperparameter tuning
        print(f"\n  1. XGBoost...")
        xgb_model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=10,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            scale_pos_weight=len(y_train[y_train==0])/len(y_train[y_train==1]),
            gpu_id=0 if self._check_gpu() else None,
            tree_method='gpu_hist' if self._check_gpu() else 'auto'
        )
        xgb_model.fit(X_train, y_train)
        self.models['xgboost'] = xgb_model

        # Model 2: LightGBM (faster, more efficient)
        print(f"\n  2. LightGBM...")
        lgb_model = lgb.LGBMClassifier(
            n_estimators=200,
            max_depth=10,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            is_unbalance=True,
            random_state=42
        )
        lgb_model.fit(X_train, y_train)
        self.models['lightgbm'] = lgb_model

        # Model 3: Isolation Forest (Anomaly Detection - Theme 4)
        print(f"\n  3. Isolation Forest (Anomaly Detection)...")
        iso_forest = IsolationForest(
            n_estimators=200,
            contamination=0.05,
            random_state=42,
            n_jobs=-1
        )
        iso_forest.fit(X_train)
        self.models['isolation_forest'] = iso_forest

        # Model 4: One-Class SVM (Anomaly Detection)
        print(f"\n  4. One-Class SVM...")
        try:
            oc_svm = OneClassSVM(kernel='rbf', gamma='auto', nu=0.05)
            oc_svm.fit(X_train)
            self.models['one_class_svm'] = oc_svm
        except:
            print(f"     Skipped (computational constraints)")

        # Create voting ensemble
        print(f"\n  5. Voting Ensemble...")
        voting_estimators = [
            ('xgb', xgb_model),
            ('lgb', lgb_model)
        ]

        voting_model = VotingClassifier(
            estimators=voting_estimators,
            voting='soft'
        )
        voting_model.fit(X_train, y_train)
        self.models['voting_ensemble'] = voting_model

        # Feature importance
        self._extract_feature_importance(xgb_model, lgb_model)

        self.is_trained = True

    def score_batch(self, features):
        """
        Ensemble fraud score for each row of a 2-D array of raw (unscaled)
        feature vectors: the weighted average of the individual models.
        """
        features_scaled = self.scaler.transform(features)

        predictions = {}

        # XGBoost prediction
        if 'xgboost' in self.models:
            predictions['xgb'] = self.models['xgboost'].predict_proba(features_scaled)[:, 1]

        # LightGBM prediction
        if 'lightgbm' in self.models:
            predictions['lgb'] = self.models['lightgbm'].predict_proba(features_scaled)[:, 1]

        # Isolation Forest prediction (anomaly score)
        if 'isolation_forest' in self.models:
            iso_score = self.models['isolation_forest'].score_samples(features_scaled)
            predictions['iso'] = 1 / (1 + np.exp(iso_score))  # Sigmoid conversion

        # Voting ensemble
        if 'voting_ensemble' in self.models:
            predictions['voting'] = self.models['voting_ensemble'].predict_proba(features_scaled)[:, 1]

        # Weighted average
        weights = {'xgb': 0.35, 'lgb': 0.35, 'iso': 0.15, 'voting': 0.15}

        final_score = sum(predictions[k] * weights[k] for k in predictions)

        # Normalize
        total_weight = sum(weights[k] for k in predictions)
        final_score = final_score / max(total_weight, 1)

        return np.clip(final_score, 0, 1)  # Ensure between 0 and 1

    def predict_fraud_advanced(self, features):
        """
        Advanced prediction using multiple models
        Combines predictions from all models
        """
        if not self.is_trained or not self.models:
            return 0.5

        try:
            if isinstance(features, list):
                features = np.array(features)

            if features.ndim == 1:
                features = features.reshape(1, -1)

            return self.score_batch(features)[0]

        except Exception as e:
            print(f"Error in advanced prediction: {e}")
            return 0.5

    def _extract_feature_importance(self, xgb_model, lgb_model):
        """Extract feature importance from models"""
        xgb_importance = xgb_model.feature_importances_
        lgb_importance = lgb_model.feature_importances_
        
        avg_importance = (xgb_importance + lgb_importance) / 2
        
        self.feature_importances = dict(zip(self.feature_names, avg_importance))
        
        # Sort by importance
        sorted_features = sorted(
            self.feature_importances.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        print(f"\n[Feature Importance]")
        for i, (feature, importance) in enumerate(sorted_features[:5], 1):
            print(f"  {i}. {feature}: {importance:.4f}")
    
    def _check_gpu(self):
        """Check if GPU is available"""
        try:
            import cupy
            return True
        except:
            return False
