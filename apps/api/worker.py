"""Durable single-host worker. Start separately from the FastAPI server."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .store import Store, pack, update_run

ROOT = Path(__file__).resolve().parents[2]


def process_once(store, runner=None):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        # Recover work abandoned by a dead worker; do not repeat paid model calls.
        for row in db.execute("SELECT * FROM runs WHERE status='running'").fetchall():
            state = json.loads(row['state'])
            if state.get('lease_until', '') < datetime.now(timezone.utc).isoformat():
                run = json.loads(row['payload'])
                run.update(status='failed', error='worker_interrupted')
                update_run(db, run, state)
        row = db.execute("SELECT * FROM runs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
        if not row:
            return False
        run, state = json.loads(row['payload']), json.loads(row['state'])
        run['status'] = 'running'
        state['lease_until'] = (datetime.now(timezone.utc) + timedelta(minutes=6)).isoformat()
        update_run(db, run, state)
    try:
        data = {**state, 'mode': run['mode'], 'draft': run['draft']}
        if runner:
            result = runner(data)
        else:
            env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'SYSTEMROOT', 'OPENAI_API_KEY', 'GITHUB_TOKEN', 'NOTEBOOK_SANDBOX_IMAGE')}
            env.update(PYTHON_DOTENV_DISABLED='1', PYTHONDONTWRITEBYTECODE='1', LANGSMITH_TRACING='false', LANGCHAIN_TRACING_V2='false')
            proc = subprocess.Popen([sys.executable, str(ROOT / 'apps/api/legacy_runner.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            started = time.monotonic()
            initial = pack(data)
            while True:
                try:
                    stdout, _ = proc.communicate(input=initial, timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    initial = None
                    with store.connect() as db:
                        current = db.execute('SELECT status FROM runs WHERE id=?', (run['id'],)).fetchone()
                    if current['status'] == 'cancelled' or time.monotonic() - started > 300:
                        proc.terminate()
                        try:
                            proc.communicate(timeout=12)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.communicate()
                        raise RuntimeError('cancelled or timeout')
            if proc.returncode:
                raise RuntimeError('agent failed')
            result = json.loads(stdout)
        if not isinstance(result.get('draft'), dict):
            raise ValueError('invalid draft')
        run['draft'] = result['draft']
        if state['phase'] == 'finalize':
            if not isinstance(result.get('output'), str) or not result['output']:
                raise ValueError('empty output')
            run.update(status='succeeded', output=result['output'])
        else:
            run['status'] = 'waiting_review'
    except Exception:
        run.update(status='failed', error='agent_execution_failed')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute('SELECT status FROM runs WHERE id=?', (run['id'],)).fetchone()
        if current and current['status'] == 'running':
            update_run(db, run, state)
    return True


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    store = Store(os.getenv('API_DATABASE', str(ROOT / 'artifacts/api/service.sqlite3')))
    print('Educator worker ready', flush=True)
    while True:
        if not process_once(store):
            time.sleep(1)
