"""
RESULTS SUMMARY
The study's measured results, condensed for the dashboard's research page

Reads the JSON files in results/ and returns only what the page shows: medians
and percentiles, not every individual run, and a one-line description of the
machine instead of the full environment record. Nothing is computed here that
is not in those files, so the page cannot drift from the results.

A file that is missing or unreadable leaves its section as None and is listed
in 'missing', so the page can say so instead of failing.
"""

import json
from pathlib import Path
from statistics import median

RESULTS_DIR = Path(__file__).resolve().parent / 'results'
MODES = ('external_batch', 'in_database', 'application')


def _load(name, directory):
    try:
        return json.loads((Path(directory) / name).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _row(arch):
    """One architecture's figures at one load, reduced to what the page shows"""
    latency = arch['decision_latency_ms']
    memory = arch.get('peak_memory_mb') or {}
    return {
        'p50_ms': latency['p50'],
        'p95_ms': latency['p95'],
        'p99_ms': latency['p99'],
        'achieved_rate_per_s': arch.get('achieved_rate_per_s'),
        'cpu_s_per_1000': (arch.get('cpu_s_per_1000_txn') or {}).get('total'),
        'memory_mb': (memory.get('application') or 0) + (memory.get('database') or 0),
        'saturated': bool(arch.get('saturated', False)),
    }


def _machine(environment):
    """A one-line description of the test machine (no versions or commit ids)"""
    if not environment:
        return None
    return (f"one laptop with {environment.get('physical_cores')} physical / "
            f"{environment.get('logical_cores')} logical processor cores and "
            f"{environment.get('total_memory_gb')} GB of memory, PostgreSQL {environment.get('postgres_version')}, "
            f"{environment.get('network', 'loopback')}")


def _detection(data):
    if not data:
        return None
    ensemble = data['models']['ensemble']
    real = ensemble['real_prevalence']
    interval = data['ensemble_ci_95_real_prevalence']
    metrics = {name: {'value': real[name], 'low': interval[name][0], 'high': interval[name][1]}
               for name in ('precision', 'recall', 'f1', 'pr_auc', 'fpr')}
    return {
        'metrics': metrics,
        'precision_before_prevalence_restored': ensemble['as_sampled']['precision'],
        'test_transactions': data['test']['rows'],
        'test_frauds': data['test']['fraud'],
        'split': data['split'],
    }


def _baseline(data):
    if not data:
        return None
    return {
        'rate_per_s': data['arrival_rate_per_s'],
        'transactions': data['transactions'],
        'runs': data['runs'],
        'batch_interval_s': data['batch_interval_s'],
        'architectures': {mode: {**_row(arch),
                                 'peak_memory_application_mb': arch['peak_memory_mb']['application'],
                                 'peak_memory_database_mb': arch['peak_memory_mb']['database'],
                                 'max_score_difference': arch.get('max_score_difference')}
                          for mode, arch in data['architectures'].items()},
    }


def _sweep(data):
    if not data:
        return None
    busy_starts = 0
    runs = 0
    for point in data['points']:
        for state in point.get('machine_state_before_each_run', []):
            runs += 1
            busy_starts += 1 if state.get('cpu_percent', 0) > 25 else 0
    return {
        'machine': _machine(data.get('environment')),
        'date': (data.get('environment') or {}).get('date', '')[:10],
        'duration_s': data['settings']['duration_s'],
        'runs_per_cell': data['settings']['runs'],
        'batch_interval_s': data['settings']['batch_interval_s'],
        'runs_total': runs,
        'runs_started_busy': busy_starts,
        'points': [{'rate_per_s': p['rate_per_s'], 'connections': p['connections'],
                    'transactions': p['transactions'],
                    'architectures': {m: _row(a) for m, a in p['architectures'].items()}}
                   for p in data['points']],
    }


def _network(data):
    if not data:
        return None
    others = [c['other_programs_cpu_percent'] for p in data['points'] for c in p.get('run_conditions', [])]
    settings = data['settings']
    return {
        'machine': _machine(data.get('environment')),
        'date': (data.get('environment') or {}).get('date', '')[:10],
        'rate_per_s': settings['rate_per_s'],
        'connections': settings['connections'],
        'transactions': settings['transactions'],
        'runs_per_cell': settings['runs'],
        'median_other_programs_cpu_percent': round(median(others), 1) if others else None,
        'points': [{'round_trip_ms': p['measured_round_trip_ms']['median_ms'],
                    'one_way_ms': p['one_way_ms'], 'reads': p['lookups'],
                    'architectures': {m: _row(a) for m, a in p['architectures'].items()}}
                   for p in data['points']],
    }


def build_summary(directory=RESULTS_DIR):
    """The summary of every result file, with any missing file listed"""
    files = {
        'detection': ('evaluation_metrics.json', _detection),
        'baseline': ('architecture_benchmark.json', _baseline),
        'sweep': ('rate_sweep.json', _sweep),
        'network': ('network_latency.json', _network),
    }
    summary = {'missing': []}
    for key, (filename, condense) in files.items():
        data = _load(filename, directory)
        if data is None:
            summary[key] = None
            summary['missing'].append(filename)
        else:
            summary[key] = condense(data)
    summary['modes'] = list(MODES)
    summary['source_files'] = [name for name, _ in files.values()]
    return summary
