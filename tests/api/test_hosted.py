import json
from unittest.mock import AsyncMock

from test_service import service, course, document, create_run
from apps.api.worker import process_once
from apps.api import retrieval


def test_search_scope_empty_results_and_delete(service):
    client, store = service
    c = course(client); d = document(client, c)
    response = client.post(f'/v1/courses/{c}/search', json={'query': '지도학습의 원리'})
    assert response.status_code == 200
    citation = response.json()['results'][0]
    assert citation['document_id'] == d and citation['chunk_id'] and citation['page'] == 1
    assert client.post(f'/v1/courses/{c}/search', json={'query': 'unrelatedastronomy'}).json()['results'] == []
    other = course(client)
    assert client.post(f'/v1/courses/{other}/search', json={'query': '지도학습', 'document_ids': [d]}).status_code == 404
    client.headers['Authorization'] = 'Bearer bob-secret'
    assert client.post(f'/v1/courses/{c}/search', json={'query': '지도학습'}).status_code == 404
    client.headers['Authorization'] = 'Bearer alice-secret'
    assert client.delete(f'/v1/documents/{d}').status_code == 204
    assert client.post(f'/v1/courses/{c}/search', json={'query': '지도학습'}).json()['results'] == []


def test_hybrid_retrieval_persists_vectors_and_filters_no_evidence(monkeypatch):
    monkeypatch.setattr(retrieval, 'embed', lambda texts: [[1.,0.] for _ in texts])
    data = retrieval.index_document('doc', {'pages': ['A completely distinct phrase']}, semantic=True)
    meta = {'id': 'doc', 'filename': 'synthetic.txt'}
    assert retrieval.search([(meta, data)], 'synonym', semantic=True)[0]['document_id'] == 'doc'
    monkeypatch.setattr(retrieval, 'embed', lambda texts: [[0.,1.] for _ in texts])
    assert retrieval.search([(meta, data)], 'synonym', semantic=True) == []


def test_failed_retry_and_course_deletion(service):
    client, store = service
    c = course(client); d = document(client, c); r = create_run(client, c, d).json()['id']
    assert client.delete(f'/v1/courses/{c}').status_code == 409
    process_once(store, runner=lambda data: (_ for _ in ()).throw(RuntimeError('synthetic')))
    assert client.post(f'/v1/runs/{r}/retries', json={'expected_revision': 2}).status_code == 409
    assert client.post(f'/v1/runs/{r}/retries', json={'expected_revision': 1}).status_code == 202
    process_once(store)
    assert client.post(f'/v1/runs/{r}/retries', json={'expected_revision': 1}).status_code == 409
    assert client.delete(f'/v1/courses/{c}').status_code == 204
    assert client.get(f'/v1/runs/{r}').status_code == 404
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM documents').fetchone()[0] == 0


def test_queue_publication_failure_is_durable_and_retryable(service, monkeypatch):
    from apps.api.queueing import schedule
    from vercel import queue
    client, store = service
    c = course(client); d = document(client, c); run = create_run(client, c, d).json()
    monkeypatch.setenv('JOB_BACKEND', 'vercel')
    send = AsyncMock(side_effect=RuntimeError('provider outage'))
    monkeypatch.setattr(queue, 'send', send)
    result = schedule(store, run)
    assert result['error'] == 'queue_unavailable'
    assert send.call_args.args[1] == {'run_id': run['id']}
    send.side_effect = None
    assert client.post(f"/v1/runs/{run['id']}/retries", json={'expected_revision': 1}).status_code == 202
    assert send.await_count == 2


def test_consumer_claims_only_addressed_run_once(service):
    client, store = service
    c = course(client); d = document(client, c)
    a = create_run(client, c, d).json()['id']; b = create_run(client, c, d).json()['id']
    assert process_once(store, run_id=b)
    assert client.get(f'/v1/runs/{a}').json()['status'] == 'queued'
    assert not process_once(store, run_id=b)


def test_polling_recovers_expired_job_and_rejects_foreign_retry(service):
    from apps.api.store import pack
    client, store = service
    c = course(client); d = document(client, c); run = create_run(client, c, d).json()
    with store.connect() as db:
        row = db.execute('SELECT state FROM runs WHERE id=?', (run['id'],)).fetchone()
        state = json.loads(row['state']); state['lease_until'] = '2000-01-01T00:00:00+00:00'
        run['status'] = 'running'
        db.execute('UPDATE runs SET status=?,payload=?,state=? WHERE id=?', ('running', pack(run), pack(state), run['id']))
    polled = client.get(f'/v1/courses/{c}/runs').json()[0]
    assert polled['status'] == 'failed' and polled['error'] == 'worker_interrupted'
    client.headers['Authorization'] = 'Bearer bob-secret'
    assert client.post(f"/v1/runs/{run['id']}/retries", json={'expected_revision': 1}).status_code == 404


def test_invites_are_admin_only_hashed_isolated_and_revocable(tmp_path, monkeypatch):
    from apps.api.main import create_app
    from fastapi.testclient import TestClient
    monkeypatch.setenv('API_ADMIN_IDS', 'admin')
    app = create_app(tmp_path/'invites.sqlite3', tokens={'admin-secret':'admin','other-secret':'other'})
    client = TestClient(app, headers={'Authorization':'Bearer admin-secret'})
    invitation = client.post('/v1/invitations').json()
    assert len(invitation['token']) >= 32
    assert 'token' not in client.get('/v1/invitations').json()[0]
    with app.state.store.connect() as db:
        assert invitation['token'] not in str(dict(db.execute('SELECT * FROM invitations').fetchone()))
    client.headers['Authorization'] = 'Bearer '+invitation['token']
    assert client.get('/v1/me').json()['admin'] is False
    assert client.post('/v1/invitations').status_code == 403
    c = course(client)
    client.headers['Authorization'] = 'Bearer other-secret'
    assert client.get(f'/v1/courses/{c}/documents').status_code == 404
    assert client.delete('/v1/invitations/'+invitation['id']).status_code == 403
    client.headers['Authorization'] = 'Bearer admin-secret'
    assert client.delete('/v1/invitations/'+invitation['id']).status_code == 204
    client.headers['Authorization'] = 'Bearer '+invitation['token']
    assert client.get('/v1/me').status_code == 401
