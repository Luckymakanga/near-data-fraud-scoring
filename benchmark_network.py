"""
NETWORK LATENCY TEST
Does distance between the application and the database change which
architecture is better?

On one machine the application and the database are a fraction of a
millisecond apart. A bank's application servers and database may not be.
This puts a delaying TCP relay (latency_proxy.py) between the application tier
and PostgreSQL, so every statement the application sends pays an extra
round trip, and repeats the three architectures at several distances:

- external_batch: the inserts and the batch scorer's polls cross the network;
  the scorer fetches what it needs in a few set-based queries per poll.
- in_database: the application only inserts the row (one round trip); scoring,
  and any reads scoring needs, happen inside the database.
- application: the application reads what scoring needs over the network,
  scores, then inserts.

The second factor, --lookups, is the number of stored-data reads (customer
history, merchant statistics) each transaction needs before it can be
scored. The benchmark's model only uses features that arrive with the
transaction, so with 0 lookups the two synchronous designs pay exactly one
round trip each and network distance cannot separate them. With lookups > 0
the application pays one round trip per read and the in-database trigger
pays none; the reads are a stand-in (the values are not used by the model,
so scores do not change) and the number is a parameter to vary, not a
measurement of any real bank.

The delaying relay adds fixed latency only: no bandwidth limit, jitter or
packet loss. The round trip actually obtained is measured and recorded for
every distance, and results should be read against that, not the setting.

CPU used by other programs during each run is estimated and recorded, and
each run waits (up to a few minutes) for a quiet machine before starting.

Usage:
    python benchmark_db.py start
    python benchmark_network.py --wait-quiet 180
    python benchmark_network.py --one-way-ms 0 25 --lookups 0 3 --runs 1 --duration 10
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import psutil
from dotenv import load_dotenv
from psycopg2.extensions import make_dsn, parse_dsn

from benchmark_architectures import MODES, median_of_runs, prepare_workload, run_mode
from benchmark_sweep import environment, is_quiet, machine_state, wait_until_quiet
from latency_proxy import measure_round_trip, start_proxy

load_dotenv()

PROXY_PORT = 5440


def process_cpu_snapshot():
    """{pid: (start time, CPU seconds so far)} for every process we may read"""
    snapshot = {}
    for process in psutil.process_iter(['create_time', 'cpu_times']):
        if process.pid == 0:  # Windows' "System Idle Process": its CPU time is idle time
            continue
        try:
            times = process.info['cpu_times']
            snapshot[process.pid] = (process.info['create_time'], times.user + times.system)
        except (psutil.Error, TypeError, AttributeError):
            pass
    return snapshot


def benchmark_pids():
    """Processes that belong to the benchmark: this one and its children, plus the
    private benchmark PostgreSQL cluster (found by its data directory)"""
    pids = set()
    me = psutil.Process()
    pids.add(me.pid)
    pids.update(child.pid for child in me.children(recursive=True))
    for process in psutil.process_iter(['cmdline']):
        try:
            if any('.benchdb' in part for part in (process.info['cmdline'] or [])):
                pids.add(process.pid)
                pids.update(child.pid for child in process.children(recursive=True))
        except (psutil.Error, TypeError):
            pass
    return pids


def other_cpu_percent(before, after, seconds, own):
    """CPU used by programs that are not part of the benchmark, as a percentage
    of the machine's capacity over the window. A lower bound: programs that
    started and finished inside the window are not seen."""
    used = 0.0
    for pid, (created, total) in after.items():
        if pid in own:
            continue
        previous = before.get(pid)
        used += total - previous[1] if previous and previous[0] == created else total
    return 100 * used / (seconds * psutil.cpu_count())


def prepare_run(budget, per_run_minutes):
    """Wait briefly for a quiet machine; report whether it was quiet at the start

    Waiting is limited per run and in total (`budget['left']`, seconds) so a
    machine that never quite settles cannot stall the whole test: once the
    budget is spent, runs start regardless and are recorded as not quiet.
    """
    state = machine_state(samples=2)
    if is_quiet(state) or budget['left'] <= 0:
        return state
    began = time.time()
    state = wait_until_quiet(min(per_run_minutes, budget['left'] / 60), samples=2)
    budget['left'] -= time.time() - began
    return state


def main():
    parser = argparse.ArgumentParser(description='Benchmark architectures at several network distances')
    parser.add_argument('--data', default='data/creditcard_sample.csv')
    parser.add_argument('--one-way-ms', type=float, nargs='+', default=[0, 1, 5, 25, 50],
                        help='delay added each way by the relay (round trip is about double, plus relay overhead)')
    parser.add_argument('--lookups', type=int, nargs='+', default=[0, 3],
                        help='stored-data reads per transaction before scoring')
    parser.add_argument('--rate', type=float, default=5, help='arrival rate (transactions/s)')
    parser.add_argument('--connections', type=int, default=4,
                        help='concurrent connections; enough that the added round trips do not saturate them')
    parser.add_argument('--duration', type=float, default=30, help='seconds of arrivals per run')
    parser.add_argument('--batch-interval', type=float, default=10)
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--modes', nargs='+', choices=MODES, default=MODES)
    parser.add_argument('--model-path', default='benchmark_model.pkl')
    parser.add_argument('--output', default='results/network_latency.json')
    parser.add_argument('--allow-noisy', action='store_true')
    parser.add_argument('--wait-quiet', type=float, default=0, metavar='MINUTES',
                        help='wait up to this long for a quiet machine before starting')
    parser.add_argument('--run-wait-minutes', type=float, default=1,
                        help='longest to wait for a quiet machine before any one run')
    parser.add_argument('--wait-budget-minutes', type=float, default=20,
                        help='total time all those per-run waits may add up to')
    args = parser.parse_args()
    budget = {'left': args.wait_budget_minutes * 60}

    dsn = os.environ.get('BENCH_DATABASE_URL')
    if not dsn:
        sys.exit("BENCH_DATABASE_URL is not set - run `python benchmark_db.py init` first")
    database = parse_dsn(dsn)
    target = (database.get('host', 'localhost'), int(database.get('port', 5432)))

    state = wait_until_quiet(args.wait_quiet) if args.wait_quiet else machine_state(samples=5)
    print(f"\n  Machine: CPU {state['cpu_percent']:.0f}% busy, {state['available_gb']} GB free")
    if not is_quiet(state) and not args.allow_noisy:
        sys.exit("\n  Not starting: the machine is busy. Close other programs, wait, or pass "
                 "--allow-noisy / --wait-quiet.")

    rows, _, reference_scores, _ = prepare_workload(args.data, args.model_path)
    n = min(len(rows), max(100, int(args.rate * args.duration)))
    subset = rows[:n]

    output = {
        'environment': environment(dsn, args.model_path),
        'settings': {'rate_per_s': args.rate, 'connections': args.connections, 'transactions': n,
                     'batch_interval_s': args.batch_interval, 'runs': args.runs,
                     'one_way_ms': args.one_way_ms, 'lookups': args.lookups, 'modes': args.modes,
                     'autocommit': True,
                     'note': 'lookups are stand-in reads; values are not used by the model'},
        'points': [],
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 80)
    print("NETWORK LATENCY TEST")
    print("=" * 80)
    for one_way in args.one_way_ms:
        proxy = start_proxy(PROXY_PORT, target, one_way)
        proxy_dsn = make_dsn(dsn, host='127.0.0.1', port=PROXY_PORT)
        try:
            round_trip = measure_round_trip(proxy_dsn)
            print(f"\n  Relay {one_way:g} ms each way -> measured round trip "
                  f"{round_trip['median_ms']:.1f} ms (95th percentile {round_trip['p95_ms']:.1f})")

            for lookups in args.lookups:
                print(f"\n  Point: round trip ~{round_trip['median_ms']:.0f} ms, {lookups} lookups per transaction, "
                      f"{n} transactions at {args.rate:g}/s over {args.connections} connections")
                runs = {mode: [] for mode in args.modes}
                conditions = []
                for run in range(1, args.runs + 1):
                    for mode in args.modes:
                        start_state = prepare_run(budget, args.run_wait_minutes)
                        own = benchmark_pids()
                        before, started = process_cpu_snapshot(), time.time()
                        print(f"    run {run}/{args.runs}: {mode}...", flush=True)
                        scores, measured = run_mode(
                            mode, dsn, subset, args.rate, args.batch_interval, args.model_path,
                            args.connections, app_dsn=proxy_dsn, lookups=lookups, autocommit=True)
                        own |= benchmark_pids()
                        noise = other_cpu_percent(before, process_cpu_snapshot(), time.time() - started, own)
                        measured['max_score_difference'] = float(np.abs(scores - reference_scores[:n]).max())
                        runs[mode].append(measured)
                        conditions.append({'run': run, 'mode': mode,
                                           'quiet_at_start': is_quiet(start_state),
                                           'cpu_percent_at_start': start_state['cpu_percent'],
                                           'available_gb_at_start': start_state['available_gb'],
                                           'other_programs_cpu_percent': round(noise, 1)})

                summary = {mode: median_of_runs(measured) for mode, measured in runs.items()}
                output['points'].append({
                    'one_way_ms': one_way, 'measured_round_trip_ms': round_trip, 'lookups': lookups,
                    'architectures': summary, 'individual_runs': runs, 'run_conditions': conditions,
                })
                output_path.write_text(json.dumps(output, indent=2))

                noisy = sum(1 for c in conditions if not c['quiet_at_start'] or c['other_programs_cpu_percent'] > 5)
                for mode, r in summary.items():
                    d = r['decision_latency_ms']
                    print(f"    {mode:<15} decision p50 {d['p50']:>8.1f} ms  p99 {d['p99']:>8.1f} ms  "
                          f"achieved {r['achieved_rate_per_s']:>5.1f}/s  CPU {r['cpu_s_per_1000_txn']['total']:>6.1f} s/1000")
                if noisy:
                    print(f"    ({noisy} of {len(conditions)} runs had a busy machine or >5% CPU from other programs)")
        finally:
            proxy.terminate()
            proxy.join()

    print(f"\n✓ Results written to {output_path}")


if __name__ == "__main__":
    main()
