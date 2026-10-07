"""
BENCHMARK DATABASE
A private PostgreSQL cluster for the architecture benchmark

The in-database architecture scores transactions with PL/Python
(plpython3u), which needs a superuser to install and a Python the server
process can load. Rather than change the main PostgreSQL service, this
runs a second, throwaway cluster under the current user account on its
own port, started with this interpreter on its PATH so the database
loads the same Python and the same installed libraries as the benchmark.

PostgreSQL's plpython3u is built against one specific Python minor
version (3.13 for the PostgreSQL 18 Windows installer); run this with
that version.

Usage:
    python benchmark_db.py init     # create the cluster (once)
    python benchmark_db.py start
    python benchmark_db.py stop

PG_BIN (environment or .env) must point at PostgreSQL's bin directory if
its tools are not on PATH.
"""

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / '.benchdb'
ENV_FILE = PROJECT_DIR / '.env'
PORT = 5433
DB_NAME = 'fraud_bench'


def pg_tool(name):
    """Locate a PostgreSQL command-line tool"""
    path = shutil.which(name, path=os.environ.get('PG_BIN'))
    if not path:
        sys.exit(f"Could not find {name} - set PG_BIN to PostgreSQL's bin directory")
    return path


def run(command, **kwargs):
    # Detached from our stdio: pg_ctl hands its handles to the server it
    # starts, which would otherwise keep a calling shell waiting forever.
    subprocess.run(command, check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def start():
    """Start the cluster with this Python first on the server's PATH"""
    env = os.environ.copy()
    env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env['PATH']
    env['PYTHONHOME'] = sys.base_prefix

    run([pg_tool('pg_ctl'), '-D', str(DATA_DIR), '-l', str(DATA_DIR / 'server.log'),
         '-o', f'-p {PORT} -c listen_addresses=localhost', '-w', 'start'], env=env)
    print(f"✓ Benchmark database running on port {PORT}")


def stop():
    run([pg_tool('pg_ctl'), '-D', str(DATA_DIR), '-m', 'fast', '-w', 'stop'])
    print("✓ Benchmark database stopped")


def init():
    """Create the cluster, record its connection string in .env, and start it"""
    if DATA_DIR.exists():
        sys.exit(f"{DATA_DIR} already exists - delete it to start over")

    password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory() as tmp:
        password_file = Path(tmp) / 'pwfile'
        password_file.write_text(password)
        run([pg_tool('initdb'), '-D', str(DATA_DIR), '-U', 'postgres', '-E', 'UTF8',
             '--locale=C', '--auth=scram-sha-256', f'--pwfile={password_file}'])

    with open(ENV_FILE, 'a') as f:
        f.write(f"\nBENCH_DATABASE_URL=postgresql://postgres:{password}@localhost:{PORT}/{DB_NAME}\n")

    start()

    conn = psycopg2.connect(host='localhost', port=PORT, user='postgres',
                            password=password, dbname='postgres')
    conn.autocommit = True
    conn.cursor().execute(f'CREATE DATABASE {DB_NAME}')
    conn.close()
    print(f"✓ Created database {DB_NAME}; BENCH_DATABASE_URL written to {ENV_FILE.name}")


if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    commands = {'init': init, 'start': start, 'stop': stop}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(__doc__)
    commands[sys.argv[1]]()
