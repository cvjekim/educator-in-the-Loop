import asyncio
import json
from fastapi.testclient import TestClient
from apps.api.main import create_app
from apps.api.events import stream


def test_stream_authorization(tmp_path):
    app=create_app(tmp_path/'events.sqlite3',tokens={'a':'alice','b':'bob'},mode='demo')
    client=TestClient(app)
    c=client.post('/v1/courses',headers={'Authorization':'Bearer a'},json={'title':'Synthetic'}).json()['id']
    assert client.get(f'/v1/courses/{c}/events').status_code==401
    assert client.get(f'/v1/courses/{c}/events',headers={'Authorization':'Bearer b'}).status_code==404


def exercise_stream(store, course_id, owner):
    calls=[]
    def snapshot():
        calls.append(True)
        with store.connect() as db:
            return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM courses WHERE owner=? AND id=?',(owner,course_id))]
    def change(title,rollback=False):
        try:
            with store.connect() as db:
                row=db.execute('SELECT payload FROM courses WHERE id=?',(course_id,)).fetchone()
                data=json.loads(row['payload']);data['title']=title
                db.execute('UPDATE courses SET payload=? WHERE id=?',(json.dumps(data),course_id))
                if rollback:raise ValueError('synthetic rollback')
        except ValueError:pass
    async def check():
        gen=stream(store,course_id,snapshot,duration=10,heartbeat=.15)
        try:
            assert 'runs.snapshot' in await anext(gen)
            assert len(calls)==1
            # Heartbeats must not query the database.
            assert await anext(gen)==': keepalive\n\n'
            assert len(calls)==1
            await asyncio.to_thread(change,'rolled back',True)
            assert await anext(gen)==': keepalive\n\n'
            assert len(calls)==1
            await asyncio.to_thread(change,'committed')
            result=await asyncio.wait_for(anext(gen),5)
            assert 'committed' in result
            assert len(calls)==2
        finally:await gen.aclose()
        # Reconnect receives authoritative current state, including missed changes.
        await asyncio.to_thread(change,'during disconnect')
        again=stream(store,course_id,snapshot,duration=10)
        try:assert 'during disconnect' in await anext(again)
        finally:await again.aclose()
    asyncio.run(check())


def test_local_commit_notifications_and_reconnect(tmp_path):
    app=create_app(tmp_path/'events.sqlite3',tokens={'a':'alice'},mode='demo')
    client=TestClient(app,headers={'Authorization':'Bearer a'})
    c=client.post('/v1/courses',json={'title':'Synthetic'}).json()['id']
    exercise_stream(app.state.store,c,'alice')
