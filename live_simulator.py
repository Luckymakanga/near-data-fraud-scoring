"""
LIVE TRANSACTION SIMULATOR

The system only ever scores a transaction when something calls
POST /api/transactions/analyze - there's no real bank or payment
processor feeding it live data. This script stands in for that: it
draws real rows from the training dataset and posts them to the API
at a randomized interval, so the admin dashboard shows transactions
arriving and getting flagged continuously instead of only on demand.

Run it locally whenever you want the "live" effect - e.g. during a
demo or while watching the dashboard. It's not meant to run 24/7
(Render's free tier has no free always-on background worker option).

Usage:
    python live_simulator.py
    python live_simulator.py --api-url https://fraud-detection-api-865q.onrender.com
    python live_simulator.py --min-interval 10 --max-interval 30
"""

import argparse
import random
import sys
import time
import uuid

import pandas as pd
import requests

CUSTOMERS = [f'CUST{i:03d}' for i in range(1, 11)]
PCA_FEATURES = [f'V{i}' for i in range(1, 29)]


def login(api_url, username, password):
    resp = requests.post(
        f'{api_url}/api/auth/login',
        json={'username': username, 'password': password},
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()['token']


def build_transaction(row):
    txn = {
        'transaction_id': f'LIVE{uuid.uuid4().hex[:8].upper()}',
        'customer_id': random.choice(CUSTOMERS),
        'amount': float(row['Amount']),
        'Time': float(row['Time']),
        'Amount': float(row['Amount']),
    }
    for name in PCA_FEATURES:
        txn[name] = float(row[name])
    return txn


def analyze(api_url, token, transaction):
    resp = requests.post(
        f'{api_url}/api/transactions/analyze',
        json=transaction,
        headers={'Authorization': f'Bearer {token}'},
        timeout=30
    )
    return resp


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--api-url', default='http://localhost:5000', help='Base URL of the fraud detection API')
    parser.add_argument('--data-path', default='data/creditcard_sample.csv', help='CSV to draw sample transactions from')
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password', default='admin')
    parser.add_argument('--min-interval', type=float, default=75, help='Minimum seconds between transactions')
    parser.add_argument('--max-interval', type=float, default=110, help='Maximum seconds between transactions')
    args = parser.parse_args()

    if args.min_interval > args.max_interval:
        parser.error('--min-interval must be <= --max-interval')

    print(f"Loading transactions from {args.data_path}...")
    df = pd.read_csv(args.data_path)
    print(f"  {len(df)} transactions available to draw from")

    print(f"Logging in to {args.api_url}...")
    token = login(args.api_url, args.username, args.password)
    print("  Logged in")

    print(f"\nSimulating live transactions every {args.min_interval:.0f}-{args.max_interval:.0f}s "
          f"(Ctrl+C to stop)\n{'-' * 80}")

    count = 0
    while True:
        row = df.sample(1).iloc[0]
        transaction = build_transaction(row)

        try:
            resp = analyze(args.api_url, token, transaction)

            if resp.status_code == 401:
                print("  Token expired, logging in again...")
                token = login(args.api_url, args.username, args.password)
                resp = analyze(args.api_url, token, transaction)

            if resp.status_code == 429:
                print("  Rate limited - backing off for 60s")
                time.sleep(60)
                continue

            resp.raise_for_status()
            result = resp.json()['result']
            count += 1

            marker = "FRAUD ALERT" if result['is_fraud'] else "ok"
            print(
                f"[{count:>4}] {result['transaction_id']} {result['customer_id']:8s} "
                f"amount={result['amount']:>10.2f}  score={result['fraud_score']:>6.1%}  "
                f"decision={result['decision']:<8s} ({marker})"
            )
        except requests.RequestException as e:
            print(f"  Error submitting transaction: {e}")

        time.sleep(random.uniform(args.min_interval, args.max_interval))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nSimulator stopped.")
        sys.exit(0)
