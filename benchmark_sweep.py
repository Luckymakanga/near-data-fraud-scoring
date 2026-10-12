"""
RATE SWEEP
How do the three scoring architectures behave as load rises?

benchmark_architectures.py compares them at one light load (10
transactions/s over one connection). This sweeps the arrival rate and the
number of concurrent connections, and records where each architecture stops
keeping up. Each point replays the first N test transactions (about
--duration seconds' worth at that rate) into PostgreSQL under every
architecture, using one fitted model, exactly as benchmark_architectures.py
does.

A point is "saturated" when the last transaction commits more than a second
late: arrivals are coming in faster than the transaction path can score and
commit them, so queueing delay grows and the latencies measured at that
point mostly reflect the backlog.

The machine's state (CPU load, free memory) is recorded before every run,
and the sweep refuses to start on a busy machine unless --allow-noisy is
given: other programs competing for CPU and memory change these numbers.
Everything still runs on one host over loopback, so network cost between
application and database is not included.

Usage:
    python benchmark_db.py start
    python benchmark_sweep.py
    python benchmark_sweep.py --points 20:1 80:1 80:4 --runs 1 --duration 20
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import argparse
import json
import os
import platform
import subprocess
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import psutil
import psycopg2
from dotenv import load_dotenv

from benchmark_architectures import MODES, median_of_runs, prepare_workload, run_mode

load_dotenv()

# rate (transactions/s) : concurrent connections
DEFAULT_POINTS = ['5:1', '10:1', '20:1', '40:1', '80:1', '160:1',
                  '80:2', '80:4', '160:2', '160:4']

MAX_QUIET_CPU_PERCENT = 20
MIN_QUIET_FREE_GB = 3
SATURATED_BACKLOG_MS = 1000


def machine_state(samples=1):
    """CPU load (mean over `samples` 2-second readings), free memory, biggest memory users"""
    cpu = float(np.mean([psutil.cpu_percent(interval=2) for _ in range(samples)]))
    memory = psutil.virtual_memory()
    others = []
    for process in psutil.process_iter(['name', 'memory_info']):
        try:
            others.append((process.info['memory_info'].rss / 2**20, process.info['name']))
        except (psutil.Error, TypeError, AttributeError):
            pass
    others.sort(reverse=True)
    return {
        'cpu_percent': cpu,
        'available_gb': round(memory.available / 2**30, 2),
        'top_memory_processes': [f'{name} {mb:.0f} MB' for mb, name in others[:5]],
    }


def is_quiet(state):
    return state['cpu_percent'] <= MAX_QUIET_CPU_PERCENT and state['available_gb'] >= MIN_QUIET_FREE_GB


def wait_until_quiet(minutes, samples=10):
    """Poll until the machine reads quiet (mean of `samples` 2-second readings), or give up"""
    deadline = time.time() + minutes * 60
    last_report = 0
    while True:
        state = machine_state(samples=samples)
        if is_quiet(state):
            return state
        if time.time() > deadline:
            return state
        if time.time() - last_report > 300:
            print(f"  Waiting for a quiet machine: CPU {state['cpu_percent']:.0f}% busy, "
                  f"{state['available_gb']} GB free ({time.strftime('%H:%M')})", flush=True)
            last_report = time.time()
        time.sleep(30)


def git_state():
    def git(*args):
        return subprocess.run(['git', *args], capture_output=True, text=True).stdout.strip()
    return {'commit': git('rev-parse', '--short', 'HEAD'), 'uncommitted_changes': bool(git('status', '--porcelain'))}


def environment(dsn, model_path):
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute('SHOW server_version')
    postgres_version = cur.fetchone()[0]
    conn.close()
    return {
        'date': datetime.now().isoformat(timespec='seconds'),
        'platform': platform.platform(),
        'python': platform.python_version(),
        'logical_cores': psutil.cpu_count(),
        'physical_cores': psutil.cpu_count(logical=False),
        'total_memory_gb': round(psutil.virtual_memory().total / 2**30, 1),
        'postgres_version': postgres_version,
        'model_file_mb': round(Path(model_path).stat().st_size / 2**20, 1),
        'network': 'loopback (application and database on one host)',
        **git_state(),
    }


def parse_point(text):
    rate, _, connections = text.partition(':')
    return float(rate), int(connections or 1)


def main():
    parser = argparse.ArgumentParser(description='Sweep arrival rate and connections')
    parser.add_argument('--data', default='data/creditcard_sample.csv')
    parser.add_argument('--points', nargs='+', default=DEFAULT_POINTS,
                        help="RATE:CONNECTIONS pairs, e.g. 40:1 160:4")
    parser.add_argument('--duration', type=float, default=40,
                        help='seconds of arrivals per point (at least 100 transactions, '
                             'at most the whole test set)')
    parser.add_argument('--batch-interval', type=float, default=10)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--modes', nargs='+', choices=MODES, default=MODES)
    parser.add_argument('--model-path', default='benchmark_model.pkl')
    parser.add_argument('--output', default='results/rate_sweep.json')
    parser.add_argument('--allow-noisy', action='store_true',
                        help='run even if the machine is busy (results will be noisy)')
    parser.add_argument('--wait-quiet', type=float, default=0, metavar='MINUTES',
                        help='wait up to this long for the machine to become quiet before starting')
    args = parser.parse_args()

    dsn = os.environ.get('BENCH_DATABASE_URL')
    if not dsn:
        sys.exit("BENCH_DATABASE_URL is not set - run `python benchmark_db.py init` first")

    state = wait_until_quiet(args.wait_quiet) if args.wait_quiet else machine_state(samples=5)
    print(f"\n  Machine: CPU {state['cpu_percent']:.0f}% busy, {state['available_gb']} GB free")
    print(f"  Largest memory users: {'; '.join(state['top_memory_processes'])}")
    if not is_quiet(state):
        message = (f"the machine is busy (needs CPU under {MAX_QUIET_CPU_PERCENT}% and at least "
                   f"{MIN_QUIET_FREE_GB} GB free). Close other programs, or pass --allow-noisy "
                   "to run anyway and have the noise recorded.")
        if not args.allow_noisy:
            sys.exit("\n  Not starting: " + message)
        print("\n  WARNING: " + message)

    points = [parse_point(p) for p in args.points]
    rows, y_test, reference_scores, _ = prepare_workload(args.data, args.model_path)

    output = {
        'environment': environment(dsn, args.model_path),
        'settings': {'duration_s': args.duration, 'batch_interval_s': args.batch_interval,
                     'runs': args.runs, 'modes': args.modes, 'test_transactions_available': len(rows)},
        'noisy_machine_allowed': bool(args.allow_noisy),
        'points': [],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 80)
    print("RATE SWEEP")
    print("=" * 80)
    for rate, connections in points:
        n = min(len(rows), max(100, int(rate * args.duration)))
        subset = rows[:n]
        print(f"\n  Point: {rate:g} txn/s over {connections} connection(s), {n} transactions")
        runs = {mode: [] for mode in args.modes}
        states = []
        for run in range(1, args.runs + 1):
            for mode in args.modes:
                # CPU and free memory only: the names of other programs stay out of the results file
                reading = {k: v for k, v in machine_state().items() if k != 'top_memory_processes'}
                states.append(reading | {'run': run, 'mode': mode})
                print(f"    run {run}/{args.runs}: {mode}...", flush=True)
                scores, measured = run_mode(
                    mode, dsn, subset, rate, args.batch_interval, args.model_path, connections)
                measured['max_score_difference'] = float(np.abs(scores - reference_scores[:n]).max())
                runs[mode].append(measured)

        summary = {mode: median_of_runs(measured) for mode, measured in runs.items()}
        for mode in summary:
            summary[mode]['saturated'] = summary[mode]['final_backlog_ms'] > SATURATED_BACKLOG_MS
        output['points'].append({
            'rate_per_s': rate, 'connections': connections, 'transactions': n,
            'architectures': summary, 'individual_runs': runs, 'machine_state_before_each_run': states,
        })
        output_path.write_text(json.dumps(output, indent=2))  # keep partial results if interrupted

        for mode, r in summary.items():
            d = r['decision_latency_ms']
            memory = r['peak_memory_mb']['application'] + r['peak_memory_mb']['database']
            print(f"    {mode:<15} decision p50 {d['p50']:>8.1f} ms  p99 {d['p99']:>8.1f} ms  "
                  f"achieved {r['achieved_rate_per_s']:>6.1f}/s  CPU {r['cpu_s_per_1000_txn']['total']:>6.2f} s/1000  "
                  f"mem {memory:>5.0f} MB  {'SATURATED' if r['saturated'] else ''}")

    print(f"\n✓ Results written to {output_path}")


if __name__ == "__main__":
    main()
