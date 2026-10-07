"""
EVALUATION HARNESS
Fraud-detection metrics for the production scoring pipeline

Trains AdvancedFraudDetectionModel on the earlier part of the dataset and
scores the later part, then reports precision, recall, F1, PR-AUC and
false-positive rate against the ground-truth labels.

Two things make these numbers differ from the quick check printed during
training:

- Time-ordered split: the model is tested on transactions that happened
  after everything it was trained on, as it would be in deployment. A
  random split lets it train on transactions from the same period it is
  tested on (use --split random to see how much that flatters it).

- Real prevalence: the bundled sample keeps every fraud but only a random
  20,000 of the 284,315 non-fraud transactions, so it is 2.4% fraud
  against 0.17% in the full dataset. Each non-fraud test row therefore
  stands in for ~14 real ones, and is weighted accordingly. Recall and
  false-positive rate are unaffected by this; precision, F1 and PR-AUC
  would otherwise be overstated.

Usage:
    python evaluate.py
    python evaluate.py --split random --threshold 0.7
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    # Windows consoles default to a legacy codepage (e.g. cp1252) that can't
    # encode the checkmark characters model training prints.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, confusion_matrix, roc_auc_score
from sklearn.model_selection import train_test_split

from advanced_ml_models import AdvancedFraudDetectionModel
from feature_engineering import extract_creditcard_features

# Non-fraud rows in the full ULB dataset (284,807 rows, 492 of them fraud)
ULB_FULL_NON_FRAUD = 284_315

METRIC_NAMES = ['precision', 'recall', 'f1', 'pr_auc', 'fpr', 'roc_auc']


def load_split(data_path, split, test_size=0.2):
    """Load the dataset and split it into train/test feature arrays"""
    df = pd.read_csv(data_path)

    if split == 'time':
        df = df.sort_values('Time', kind='stable').reset_index(drop=True)
        cut = int(len(df) * (1 - test_size))
        train_df, test_df = df.iloc[:cut], df.iloc[cut:]
    else:
        train_df, test_df = train_test_split(
            df, test_size=test_size, random_state=42, stratify=df['Class']
        )

    def to_arrays(part):
        X = np.array([extract_creditcard_features(row) for row in part.to_dict('records')])
        return X, part['Class'].to_numpy()

    # Weight that scales the sampled non-fraud rows back up to their real
    # share (1.0 if the file is the full dataset rather than the sample)
    negative_weight = ULB_FULL_NON_FRAUD / (df['Class'] == 0).sum()

    return to_arrays(train_df), to_arrays(test_df), negative_weight


def compute_metrics(y_true, scores, threshold, weights=None):
    """Fraud-detection metrics at a decision threshold (plus PR-AUC / ROC-AUC)"""
    y_pred = scores > threshold
    tn, fp, fn, tp = confusion_matrix(
        y_true, y_pred, labels=[0, 1], sample_weight=weights
    ).ravel()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        'precision': float(precision),
        'recall': float(recall),
        'f1': float(f1),
        'pr_auc': float(average_precision_score(y_true, scores, sample_weight=weights)),
        'fpr': float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0,
        'roc_auc': float(roc_auc_score(y_true, scores, sample_weight=weights)),
    }


def bootstrap_ci(y_true, scores, threshold, weights, n_resamples=1000, seed=42):
    """95% confidence interval for each metric, by resampling the test set"""
    rng = np.random.default_rng(seed)
    n = len(y_true)
    samples = {name: [] for name in METRIC_NAMES}

    for _ in range(n_resamples):
        idx = rng.integers(0, n, n)
        if y_true[idx].min() == y_true[idx].max():  # needs both classes
            continue
        metrics = compute_metrics(y_true[idx], scores[idx], threshold, weights[idx])
        for name in METRIC_NAMES:
            samples[name].append(metrics[name])

    return {
        name: [float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))]
        for name, values in samples.items()
    }


def main():
    parser = argparse.ArgumentParser(description='Evaluate the fraud scoring pipeline')
    parser.add_argument('--data', default='data/creditcard_sample.csv')
    parser.add_argument('--split', choices=['time', 'random'], default='time')
    parser.add_argument('--threshold', type=float, default=0.5,
                        help='score above which a transaction counts as fraud')
    parser.add_argument('--output', default='results/evaluation_metrics.json')
    args = parser.parse_args()

    (X_train, y_train), (X_test, y_test), negative_weight = load_split(args.data, args.split)

    model = AdvancedFraudDetectionModel(data_path=args.data)
    model.fit(X_train, y_train)

    # The ensemble is what process_transaction() acts on; the individual
    # classifiers are reported alongside it for comparison.
    X_test_scaled = model.scaler.transform(X_test)
    scores = {'ensemble': model.score_batch(X_test)}
    for name in ('xgboost', 'lightgbm', 'voting_ensemble'):
        scores[name] = model.models[name].predict_proba(X_test_scaled)[:, 1]

    weights = np.where(y_test == 1, 1.0, negative_weight)
    results = {
        name: {
            'as_sampled': compute_metrics(y_test, s, args.threshold),
            'real_prevalence': compute_metrics(y_test, s, args.threshold, weights),
        }
        for name, s in scores.items()
    }
    ci = bootstrap_ci(y_test, scores['ensemble'], args.threshold, weights)

    test_fraud = int(y_test.sum())
    real_prevalence = test_fraud / (test_fraud + negative_weight * (len(y_test) - test_fraud))

    print("\n" + "=" * 80)
    print("EVALUATION RESULTS")
    print("=" * 80)
    print(f"\n  Split: {args.split} | Threshold: {args.threshold}")
    print(f"  Train: {len(y_train)} rows ({int(y_train.sum())} fraud)")
    print(f"  Test:  {len(y_test)} rows ({test_fraud} fraud)")
    print(f"  Test fraud rate: {y_test.mean():.2%} as sampled, {real_prevalence:.2%} at real prevalence")

    print(f"\n[Ensemble - the score the system acts on]")
    print(f"  {'':<12}{'as sampled':>12}{'real prevalence':>18}{'95% CI':>20}")
    for name in METRIC_NAMES:
        low, high = ci[name]
        print(f"  {name:<12}{results['ensemble']['as_sampled'][name]:>12.4f}"
              f"{results['ensemble']['real_prevalence'][name]:>18.4f}"
              f"{f'{low:.4f} - {high:.4f}':>20}")

    print(f"\n[All models, at real prevalence]")
    print(f"  {'':<18}" + "".join(f"{name:>11}" for name in METRIC_NAMES))
    for model_name, result in results.items():
        print(f"  {model_name:<18}"
              + "".join(f"{result['real_prevalence'][name]:>11.4f}" for name in METRIC_NAMES))

    output = {
        'dataset': args.data,
        'split': args.split,
        'threshold': args.threshold,
        'train': {'rows': len(y_train), 'fraud': int(y_train.sum())},
        'test': {'rows': len(y_test), 'fraud': test_fraud},
        'negative_weight': float(negative_weight),
        'test_fraud_rate_as_sampled': float(y_test.mean()),
        'test_fraud_rate_real_prevalence': float(real_prevalence),
        'models': results,
        'ensemble_ci_95_real_prevalence': ci,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\n✓ Results written to {output_path}")


if __name__ == "__main__":
    main()
