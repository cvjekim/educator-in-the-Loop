"""Publish opaque job IDs only; course content remains in the private database."""
import asyncio
import json
import os

from .store import pack


def schedule(store, run):
    if os.getenv('JOB_BACKEND', 'local') != 'vercel' or run['status'] != 'queued':
        return run
    from vercel.queue import send
    with store.connect() as db:
        row = db.execute('SELECT state FROM runs WHERE id=?', (run['id'],)).fetchone()
        if not row:
            return run
        state = json.loads(row['state'])
    key = f"{run['id']}:{run['revision']}:{state['phase']}:{state.get('attempt', 0)}"
    try:
        asyncio.run(send('educator-jobs', {'run_id': run['id']}, idempotency_key=key))
    except Exception:
        # The durable DB record survives provider outages; explicit retry can republish it.
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload,status FROM runs WHERE id=?', (run['id'],)).fetchone()
            if row and row['status'] == 'queued':
                run = json.loads(row['payload'])
                run['error'] = 'queue_unavailable'
                db.execute('UPDATE runs SET payload=? WHERE id=?', (pack(run), run['id']))
    return run
