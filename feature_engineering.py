"""
FEATURE ENGINEERING - ULB Credit Card Fraud dataset schema

Shared between model training (advanced_ml_models.py) and live inference
(transaction_processor.py) so the features a model is trained on and the
features computed for a live transaction never drift apart.

The predictive features (V1-V28) are PCA-anonymized components from the
source dataset - they have no individually interpretable real-world
meaning, so this module is mostly a straight pass-through rather than
hand-engineering new signal on top of them.
"""

import numpy as np

PCA_FEATURES = [f'V{i}' for i in range(1, 29)]
FEATURE_NAMES = ['time_of_day'] + PCA_FEATURES + ['amount']


def extract_creditcard_features(transaction):
    """
    Build a feature vector (matching FEATURE_NAMES) from a raw transaction.

    Expected keys: 'Time' (seconds elapsed since the dataset's first
    transaction), 'V1'..'V28' (anonymized PCA components), 'Amount'.
    Missing V-features default to 0.0.
    """
    seconds = float(transaction.get('Time', 0) or 0)
    time_of_day = (seconds % 86400) / 86400.0  # 86400s = 1 day

    pca_values = [float(transaction.get(name, 0) or 0) for name in PCA_FEATURES]

    amount = float(transaction.get('Amount', 0) or 0)

    return np.array([time_of_day] + pca_values + [amount])
