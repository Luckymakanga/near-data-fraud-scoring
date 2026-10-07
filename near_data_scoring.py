"""
NEAR-DATA SCORING
Scoring transactions as they are stored in the database

Shared by every architecture in benchmark_architectures.py - the external
scorers import it in their own process, and the in-database trigger
imports it inside PostgreSQL - so all of them score with the same model
and the same feature code, and differ only in where that code runs.
"""

import pickle

import numpy as np

from feature_engineering import PCA_FEATURES, extract_creditcard_features

# Transaction columns as stored in the database (lower-cased dataset names)
TRANSACTION_COLUMNS = ['time'] + [name.lower() for name in PCA_FEATURES] + ['amount']


def load_model(model_path):
    """Load a fitted AdvancedFraudDetectionModel saved by the benchmark"""
    with open(model_path, 'rb') as f:
        model = pickle.load(f)

    # One thread per scoring call. For a single transaction the models'
    # default of every core is no faster (the work is too small to split)
    # but uses several times the CPU, and makes latency collapse as soon
    # as anything else on the machine wants a core. Scores are unchanged.
    for name in ('xgboost', 'lightgbm', 'isolation_forest'):
        model.models[name].set_params(n_jobs=1)
    for estimator in model.models['voting_ensemble'].estimators_:
        estimator.set_params(n_jobs=1)

    return model


def score_rows(model, rows):
    """Fraud score for each stored transaction (mappings keyed by column name)"""
    features = []
    for row in rows:
        transaction = {name: row[name.lower()] for name in PCA_FEATURES}
        transaction['Time'] = row['time']
        transaction['Amount'] = row['amount']
        features.append(extract_creditcard_features(transaction))

    return model.score_batch(np.array(features))
