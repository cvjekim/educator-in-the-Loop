"""Run against an ephemeral schema, never against existing application tables."""
import os
from uuid import uuid4
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor

import pytest
import psycopg
from fastapi.testclient import TestClient
from apps.api.main import create_app
from apps.api.worker import process_once


@pytest.fixture
def postgres_app():
    dsn = os.getenv('TEST_DATABASE_URL')
    if not dsn:
        pytest.skip('TEST_DATABASE_URL required for PostgreSQL integration')
    schema = 'test_' + uuid4().hex
    with psycopg.connect(dsn) as db:
        db.execute(psycopg.sql.SQL('CREATE SCHEMA {}').format(psycopg.sql.Identifier(schema)))
    scoped = dsn + ('&' if '?' in dsn else '?') + urlencode({'options': '-csearch_path='+schema})
    try:
        yield create_app(scoped, tokens={'synthetic-token': 'synthetic-owner'}, mode='demo')
    finally:
        with psycopg.connect(dsn) as db:
            db.execute(psycopg.sql.SQL('DROP SCHEMA {} CASCADE').format(psycopg.sql.Identifier(schema)))


def test_postgres_concurrent_enqueue_and_worker_claim(postgres_app):
    client = TestClient(postgres_app, headers={'Authorization': 'Bearer synthetic-token'})
    c = client.post('/v1/courses', json={'title': 'Synthetic', 'syllabus': 'Week 1: concepts'}).json()['id']
    def enqueue(_):
        return client.post(f'/v1/courses/{c}/runs', json={'task_type':'manager','topic':'concepts'}, headers={'Idempotency-Key':'same-request-key'})
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(enqueue, range(4)))
    assert all(r.status_code == 202 for r in responses)
    assert len({r.json()['id'] for r in responses}) == 1
    run = responses[0].json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda _: process_once(postgres_app.state.store, run_id=run['id']), range(2)))
    assert claimed.count(True) == 1
    assert client.get(f"/v1/runs/{run['id']}").json()['status'] == 'waiting_review'
    assert client.post(f"/v1/runs/{run['id']}/reviews", json={'decision':'approve','expected_revision':1}).status_code == 202
    assert process_once(postgres_app.state.store, run_id=run['id'])
    assert client.get(f"/v1/runs/{run['id']}/artifact").status_code == 200
    assert client.delete(f'/v1/courses/{c}').status_code == 204
