"""
ARCHITECTURE BENCHMARK
Where should fraud scoring run relative to the transaction data?

Replays the held-out (later 20% by time) transactions into PostgreSQL at
a fixed arrival rate under each architecture, using one fitted model and
one feature pipeline throughout, so the only thing that changes is where
scoring happens:

- external_batch: the conventional pipeline. Transactions are stored
  unscored; a separate scoring process polls the database on an interval,
  pulls the unscored rows out, scores them and writes the scores back.

- in_database: near-data scoring. A PL/Python trigger scores each row
  inside PostgreSQL as it is inserted; the data never leaves the database.

- application: the deployed system's approach, for reference. The
  application scores each transaction itself, then stores it with its
  score.

Measured for each:

- ingest latency: scheduled arrival -> transaction committed (how long
  the transaction path is held up)
- decision latency: scheduled arrival -> fraud score committed
- cold start: time before a new scorer (or database session) can score
- CPU time and peak memory, split between application and database
  processes
- the detection metrics of the scores that ended up in the database

Each architecture is run several times (--runs) and the median of the
runs is reported, with every run kept in the results file.

Everything runs on one machine over loopback, so network cost between
application and database is close to zero here; on separate hosts the
external architectures would pay more for moving data than this shows.

Usage:
    python benchmark_db.py init          # once - see benchmark_db.py
    python benchmark_architectures.py
    python benchmark_architectures.py --rate 10 --batch-interval 30 --limit 500
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    # Windows consoles default to a legacy codepage (e.g. cp1252) that can't
    # encode the checkmark characters model training prints.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import argparse
import json
import multiprocessing
import os
import pickle
import time
from pathlib import Path

import numpy as np
import psutil
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor, execute_values
from dotenv import load_dotenv

from near_data_scoring import TRANSACTION_COLUMNS, load_model, score_rows

# pandas, scikit-learn and the evaluation code are imported inside main()
# rather than here: every benchmark process re-imports this module, and a
# process that only inserts rows should not carry them in its measured
# memory.

load_dotenv()

MODES = ['external_batch', 'in_database', 'application']
PROJECT_DIR = Path(__file__).resolve().parent

SCHEMA = f"""
DROP TABLE IF EXISTS bench_transactions;
CREATE TABLE bench_transactions (
    transaction_id integer PRIMARY KEY,
    {' double precision, '.join(TRANSACTION_COLUMNS)} double precision,
    fraud_score double precision
);
CREATE INDEX idx_bench_unscored ON bench_transactions (transaction_id)
    WHERE fraud_score IS NULL;

CREATE EXTENSION IF NOT EXISTS plpython3u;

-- The model is loaded once per database session and kept in SD, PL/Python's
-- per-function session cache; the trigger arguments say where to find it.
CREATE OR REPLACE FUNCTION score_transaction() RETURNS trigger AS $$
    if 'model' not in SD:
        import sys
        project_dir, model_path = TD['args']
        if project_dir not in sys.path:
            sys.path.insert(0, project_dir)
        import near_data_scoring
        SD['score_rows'] = near_data_scoring.score_rows
        SD['model'] = near_data_scoring.load_model(model_path)

    TD['new']['fraud_score'] = float(SD['score_rows'](SD['model'], [TD['new']])[0])
    return 'MODIFY'
$$ LANGUAGE plpython3u;
"""

SCORING_TRIGGER = """
CREATE TRIGGER score_on_insert BEFORE INSERT ON bench_transactions
    FOR EACH ROW EXECUTE FUNCTION score_transaction({}, {})
"""


def process_usage(pid):
    """(CPU seconds used so far, peak memory in MB) for a process"""
    process = psutil.Process(pid)
    cpu = process.cpu_times()
    memory = process.memory_info()
    # peak_wset is Windows-only; elsewhere fall back to current resident size
    return cpu.user + cpu.system, getattr(memory, 'peak_wset', memory.rss) / 2**20


def load_generator(mode, dsn, rows, rate, model_path, out_queue,
                   index=0, count=1, go=None, start_time=None):
    """Insert the transactions at a fixed arrival rate, one commit each

    With several connections, generator `index` of `count` handles every
    count-th transaction. All generators share one schedule (transaction i
    is due at start + i / rate) and wait on `go` so none starts before the
    others have finished their cold start.
    """
    ids = list(range(index, len(rows), count))
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    db_pid = conn.get_backend_pid()

    columns = ['transaction_id'] + TRANSACTION_COLUMNS
    if mode == 'application':
        columns.append('fraud_score')
    insert = sql.SQL('INSERT INTO bench_transactions ({}) VALUES ({})').format(
        sql.SQL(', ').join(map(sql.Identifier, columns)),
        sql.SQL(', ').join(sql.Placeholder() * len(columns)),
    )

    def parameters(row):
        return [row['transaction_id']] + [row[name] for name in TRANSACTION_COLUMNS]

    # Cold start: whatever has to happen before the first score comes back
    started = time.perf_counter()
    model = None
    if mode == 'application':
        model = load_model(model_path)
        score_rows(model, rows[:1])
    elif mode == 'in_database':
        cur.execute(insert, parameters(rows[0]))  # loads the model into this session
        conn.rollback()
    cold_start = time.perf_counter() - started

    app_cpu_before, _ = process_usage(os.getpid())
    db_cpu_before, _ = process_usage(db_pid)

    out_queue.put('ready')
    go.wait()
    start = start_time.value

    scheduled, committed = [], []
    for i in ids:
        row = rows[i]
        due = start + i / rate
        delay = due - time.time()
        if delay > 0:
            time.sleep(delay)

        params = parameters(row)
        if mode == 'application':
            params.append(float(score_rows(model, [row])[0]))
        cur.execute(insert, params)
        conn.commit()

        scheduled.append(due)
        committed.append(time.time())

    app_cpu, app_memory = process_usage(os.getpid())
    db_cpu, db_memory = process_usage(db_pid)
    out_queue.put({
        'ids': ids,
        'scheduled': scheduled,
        'committed': committed,
        'cold_start': cold_start,
        'app_cpu': app_cpu - app_cpu_before,
        'app_memory': app_memory,
        'db_cpu': db_cpu - db_cpu_before,
        'db_memory': db_memory,
    })
    conn.close()


def batch_scorer(dsn, model_path, interval, expected, out_queue):
    """Poll for unscored transactions, score them outside the database, write back"""
    started = time.perf_counter()
    model = load_model(model_path)
    cold_start = time.perf_counter() - started

    conn = psycopg2.connect(dsn)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    db_pid = conn.get_backend_pid()

    app_cpu_before, _ = process_usage(os.getpid())
    db_cpu_before, _ = process_usage(db_pid)
    out_queue.put('ready')

    scored_at = {}
    batches = 0
    max_batch_rows = 0
    max_batch_seconds = 0.0
    next_poll = time.time() + interval
    while len(scored_at) < expected:
        time.sleep(max(0.0, next_poll - time.time()))
        next_poll += interval
        poll_started = time.perf_counter()

        cur.execute(
            sql.SQL('SELECT transaction_id, {} FROM bench_transactions '
                    'WHERE fraud_score IS NULL ORDER BY transaction_id').format(
                sql.SQL(', ').join(map(sql.Identifier, TRANSACTION_COLUMNS)))
        )
        rows = cur.fetchall()
        if rows:
            scores = score_rows(model, rows)
            execute_values(
                cur,
                'UPDATE bench_transactions AS t SET fraud_score = v.score '
                'FROM (VALUES %s) AS v(transaction_id, score) '
                'WHERE t.transaction_id = v.transaction_id',
                [(row['transaction_id'], float(score)) for row, score in zip(rows, scores)],
                page_size=1000,
            )
            batches += 1
        conn.commit()

        now = time.time()
        for row in rows:
            scored_at[row['transaction_id']] = now
        max_batch_rows = max(max_batch_rows, len(rows))
        max_batch_seconds = max(max_batch_seconds, time.perf_counter() - poll_started)

    app_cpu, app_memory = process_usage(os.getpid())
    db_cpu, db_memory = process_usage(db_pid)
    out_queue.put({
        'scored_at': scored_at,
        'batches': batches,
        'max_batch_rows': max_batch_rows,
        'max_batch_seconds': max_batch_seconds,
        'cold_start': cold_start,
        'app_cpu': app_cpu - app_cpu_before,
        'app_memory': app_memory,
        'db_cpu': db_cpu - db_cpu_before,
        'db_memory': db_memory,
    })
    conn.close()


def wait_for(queue, processes):
    """Next message from worker process(es), failing fast if one died instead

    A worker that has already reported may exit cleanly while others are
    still running, so only a non-zero exit, or every worker having
    exited with nothing left to read, counts as a failure.
    """
    if not isinstance(processes, (list, tuple)):
        processes = [processes]
    while True:
        try:
            return queue.get(timeout=1)
        except multiprocessing.queues.Empty:
            crashed = [p for p in processes if p.exitcode not in (None, 0)]
            finished = all(not p.is_alive() for p in processes)
            if crashed or finished:
                try:
                    return queue.get(timeout=1)
                except multiprocessing.queues.Empty:
                    names = ', '.join(p.name for p in (crashed or processes))
                    raise RuntimeError(f"{names} exited without reporting (see output above)")


def latency_summary(seconds):
    ms = np.array(seconds) * 1000
    return {
        'mean': float(ms.mean()),
        'p50': float(np.percentile(ms, 50)),
        'p95': float(np.percentile(ms, 95)),
        'p99': float(np.percentile(ms, 99)),
        'max': float(ms.max()),
    }


def median_of_runs(measurements):
    """Median of each measurement across repeated runs of one architecture"""
    if isinstance(measurements[0], dict):
        return {key: median_of_runs([m[key] for m in measurements]) for key in measurements[0]}
    return float(np.median(measurements))


def run_mode(mode, dsn, rows, rate, batch_interval, model_path, connections=1):
    """Run one architecture and return its measurements and stored scores

    `connections` is the number of concurrent database connections (and, for
    the application architecture, application scorer processes) the arrivals
    are spread across. Memory is summed over them, since each holds its own
    copy of the model.
    """
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(SCHEMA)
    if mode == 'in_database':
        cur.execute(sql.SQL(SCORING_TRIGGER).format(
            sql.Literal(PROJECT_DIR.as_posix()), sql.Literal(Path(model_path).resolve().as_posix())))

    scorer = scorer_queue = None
    if mode == 'external_batch':
        scorer_queue = multiprocessing.Queue()
        scorer = multiprocessing.Process(
            target=batch_scorer, name='batch scorer',
            args=(dsn, model_path, batch_interval, len(rows), scorer_queue))
        scorer.start()
        wait_for(scorer_queue, scorer)  # 'ready'

    loader_queue = multiprocessing.Queue()
    go = multiprocessing.Event()
    start_time = multiprocessing.Value('d', 0.0)
    loaders = [
        multiprocessing.Process(
            target=load_generator, name=f'load generator {k + 1}',
            args=(mode, dsn, rows, rate, model_path, loader_queue, k, connections, go, start_time))
        for k in range(connections)
    ]
    for loader in loaders:
        loader.start()
    for _ in loaders:
        wait_for(loader_queue, loaders)  # each reports 'ready' after its cold start
    start_time.value = time.time() + 0.5
    go.set()
    loads = [wait_for(loader_queue, loaders) for _ in loaders]
    for loader in loaders:
        loader.join()

    scheduled = np.empty(len(rows))
    committed = np.empty(len(rows))
    for load in loads:
        scheduled[load['ids']] = load['scheduled']
        committed[load['ids']] = load['committed']
    ingest = committed - scheduled
    decision = ingest
    cold_start = max(load['cold_start'] for load in loads)
    app_cpu = sum(load['app_cpu'] for load in loads)
    db_cpu = sum(load['db_cpu'] for load in loads)
    app_memory = sum(load['app_memory'] for load in loads)
    db_memory = sum(load['db_memory'] for load in loads)
    extra = {}

    if scorer:
        scoring = wait_for(scorer_queue, scorer)
        scorer.join()
        decision = np.array([scoring['scored_at'][row['transaction_id']] for row in rows]) - scheduled
        cold_start = scoring['cold_start']
        app_cpu += scoring['app_cpu']
        db_cpu += scoring['db_cpu']
        # max, as in the original benchmark: the larger of the inserting and
        # the scoring side, so results stay comparable with earlier runs
        app_memory = max(app_memory, scoring['app_memory'])
        db_memory = max(db_memory, scoring['db_memory'])
        extra = {'max_batch_rows': scoring['max_batch_rows'],
                 'max_batch_seconds': scoring['max_batch_seconds']}

    cur.execute('SELECT fraud_score FROM bench_transactions ORDER BY transaction_id')
    scores = np.array([row[0] for row in cur.fetchall()], dtype=float)
    conn.close()

    per_1000 = 1000 / len(rows)
    duration = float(committed.max() - scheduled.min())
    return scores, {
        'connections': connections,
        'duration_s': duration,
        'achieved_rate_per_s': len(rows) / duration,
        'final_backlog_ms': float(ingest[np.argmax(committed)] * 1000),
        **extra,
        'ingest_latency_ms': latency_summary(ingest),
        'decision_latency_ms': latency_summary(decision),
        'cold_start_s': cold_start,
        'cpu_s_per_1000_txn': {
            'application': app_cpu * per_1000,
            'database': db_cpu * per_1000,
            'total': (app_cpu + db_cpu) * per_1000,
        },
        'peak_memory_mb': {'application': app_memory, 'database': db_memory},
    }


def prepare_workload(data_path, model_path, limit=None):
    """Fit the model on the earlier 80% by time, pickle it, and build the replay

    Returns the replayed transactions, their labels, the model's own scores
    for them (the reference every architecture must reproduce), and the
    evaluation weights that restore the real fraud prevalence.
    """
    import pandas as pd
    from advanced_ml_models import AdvancedFraudDetectionModel
    from evaluate import negative_weight, split_frame, to_arrays

    df = pd.read_csv(data_path)
    train_df, test_df = split_frame(df, 'time')
    if limit:
        test_df = test_df.iloc[:limit]

    model = AdvancedFraudDetectionModel(data_path=data_path)
    model.fit(*to_arrays(train_df))
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)

    X_test, y_test = to_arrays(test_df)
    reference_scores = model.score_batch(X_test)
    weights = np.where(y_test == 1, 1.0, negative_weight(df))

    rows = test_df.rename(columns=str.lower)[TRANSACTION_COLUMNS].to_dict('records')
    for i, row in enumerate(rows):
        row['transaction_id'] = i
    return rows, y_test, reference_scores, weights


def main():
    parser = argparse.ArgumentParser(description='Compare fraud-scoring architectures')
    parser.add_argument('--data', default='data/creditcard_sample.csv')
    parser.add_argument('--rate', type=float, default=10,
                        help='transaction arrival rate (per second)')
    parser.add_argument('--connections', type=int, default=1,
                        help='concurrent connections the arrivals are spread across')
    parser.add_argument('--batch-interval', type=float, default=10,
                        help='seconds between polls of the external batch scorer')
    parser.add_argument('--runs', type=int, default=3,
                        help='repetitions of each architecture; the median is reported')
    parser.add_argument('--limit', type=int, help='replay only the first N test transactions')
    parser.add_argument('--threshold', type=float, default=0.5)
    parser.add_argument('--modes', nargs='+', choices=MODES, default=MODES)
    parser.add_argument('--model-path', default='benchmark_model.pkl')
    parser.add_argument('--output', default='results/architecture_benchmark.json')
    args = parser.parse_args()

    dsn = os.environ.get('BENCH_DATABASE_URL')
    if not dsn:
        sys.exit("BENCH_DATABASE_URL is not set - run `python benchmark_db.py init` first")

    from evaluate import compute_metrics

    rows, y_test, reference_scores, weights = prepare_workload(
        args.data, args.model_path, args.limit)

    print("\n" + "=" * 80)
    print("ARCHITECTURE BENCHMARK")
    print("=" * 80)
    print(f"\n  {len(rows)} transactions ({int(y_test.sum())} fraud) at {args.rate:g}/s"
          f" | {args.connections} connection(s)"
          f" | batch interval {args.batch_interval:g}s | {args.runs} runs")

    # Architectures take turns within each run, rather than one finishing
    # all its runs first, so a busy spell on the machine cannot fall
    # entirely on one of them.
    runs = {mode: [] for mode in args.modes}
    for run in range(1, args.runs + 1):
        for mode in args.modes:
            print(f"\n  Run {run}/{args.runs}: {mode}...")
            scores, measured = run_mode(
                mode, dsn, rows, args.rate, args.batch_interval, args.model_path,
                args.connections)
            measured['max_score_difference'] = float(np.abs(scores - reference_scores).max())
            measured['detection_real_prevalence'] = compute_metrics(
                y_test, scores, args.threshold, weights)
            runs[mode].append(measured)

    results = {mode: median_of_runs(measured) for mode, measured in runs.items()}

    def table_row(label, value, fmt):
        print(f"  {label:<30}" + "".join(f"{format(value(results[m]), fmt):>16}" for m in results))

    print(f"\n  {f'Median of {args.runs} runs':<30}" + "".join(f"{mode:>16}" for mode in results))
    for stat in ('p50', 'p95', 'p99'):
        table_row(f"Ingest latency {stat} (ms)", lambda r: r['ingest_latency_ms'][stat], '.1f')
    for stat in ('p50', 'p95', 'p99'):
        table_row(f"Decision latency {stat} (ms)", lambda r: r['decision_latency_ms'][stat], '.1f')
    table_row("Cold start (s)", lambda r: r['cold_start_s'], '.2f')
    for part in ('application', 'database', 'total'):
        table_row(f"CPU s / 1000 txn ({part})", lambda r: r['cpu_s_per_1000_txn'][part], '.2f')
    for part in ('application', 'database'):
        table_row(f"Peak memory MB ({part})", lambda r: r['peak_memory_mb'][part], '.0f')
    for metric in ('precision', 'recall', 'f1', 'pr_auc', 'fpr'):
        table_row(metric, lambda r: r['detection_real_prevalence'][metric], '.4f')
    table_row("Max score difference", lambda r: r['max_score_difference'], '.1e')

    output = {
        'dataset': args.data,
        'transactions': len(rows),
        'fraud': int(y_test.sum()),
        'arrival_rate_per_s': args.rate,
        'connections': args.connections,
        'batch_interval_s': args.batch_interval,
        'threshold': args.threshold,
        'runs': args.runs,
        'architectures': results,
        'individual_runs': runs,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\n✓ Results written to {output_path}")


if __name__ == "__main__":
    main()
