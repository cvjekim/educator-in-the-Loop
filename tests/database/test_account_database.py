"""Actual PostgreSQL account registration, session revocation and ownership tests."""
import pytest
from fastapi import HTTPException
from apps.api.accounts import Accounts, ProfileInput
from apps.database.client import Database
from test_schema import database


def test_account_lifecycle(database):
    dsn,schema,role=database
    from apps.database.provision import provision_runtime
    provision_runtime(dsn,schema,role)
    accounts=Accounts(Database(dsn,schema,role))
    assert accounts.login('synthetic-google-a') == {'needsRegistration':True}
    a=accounts.login('synthetic-google-a',ProfileInput(name='Synthetic A',department='Teaching'))
    b=accounts.login('synthetic-google-b',ProfileInput(name='Synthetic B',department='Science'))
    assert a['profile']['id']!=b['profile']['id']
    assert accounts.resolve(a['sessionToken'])==a['profile']
    assert accounts.resolve('invalid') is None
    assert accounts.resolve(b['sessionToken'])==b['profile']
    updated=accounts.update(a['profile']['id'],ProfileInput(name='Updated',department='Learning'))
    assert accounts.resolve(a['sessionToken'])==updated
    assert accounts.resolve(b['sessionToken'])==b['profile']
    # Repeated registration cannot overwrite an existing profile or create a new user.
    again=accounts.login('synthetic-google-a',ProfileInput(name='Wrong',department='Wrong'))
    assert again['profile']==updated
    accounts.logout(a['profile']['id'],a['sessionToken'])
    assert accounts.resolve(a['sessionToken']) is None
    assert accounts.resolve(again['sessionToken'])==updated
    with accounts.database.transaction(a['profile']['id']) as db:
        assert db.execute('SELECT id FROM users WHERE id=%s',(b['profile']['id'],)).fetchone() is None
        assert db.execute('SELECT "subject" FROM "oauthAccounts"').fetchall()==[{'subject':'synthetic-google-a'}]
        db.execute('UPDATE sessions SET "expiresAt"=now()+interval \'1 second\',"createdAt"=now()-interval \'1 day\' WHERE "userId"=%s',(a['profile']['id'],))
    # Suspended accounts cannot resolve sessions or create new sessions.
    import psycopg
    from psycopg import sql
    with psycopg.connect(dsn) as db:
        db.execute(sql.SQL('UPDATE {}.users SET status=\'suspended\' WHERE id=%s').format(sql.Identifier(schema)),(a['profile']['id'],))
    assert accounts.resolve(again['sessionToken']) is None
    with pytest.raises(HTTPException) as exc:accounts.login('synthetic-google-a')
    assert exc.value.status_code==403


def test_profile_rest_uses_authenticated_identity(database,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from apps.api import accounts as module
    from apps.api.main import create_app
    dsn,schema,role=database
    monkeypatch.setenv('DATABASE_URL',dsn)
    monkeypatch.setenv('GOOGLE_CLIENT_ID','synthetic-client')
    monkeypatch.setattr(module,'Database',lambda _,**kwargs:Database(dsn,schema,role))
    monkeypatch.setattr(module,'verify_google',lambda credential,nonce,client_id:'rest-'+credential)
    app=create_app(str(tmp_path/'legacy.db'),tokens={},mode='demo')
    client=TestClient(app)
    payload={'credential':'a','nonce':'n'*32}
    assert client.post('/v1/auth/google',json=payload).json()['needsRegistration']
    result=client.post('/v1/auth/google',json={**payload,'profile':{'name':'Synthetic','department':'Teaching'}}).json()
    headers={'Authorization':'Bearer '+result['sessionToken']}
    assert client.get('/v1/me',headers=headers).json()['id']==result['profile']['id']
    assert client.get('/v1/profile',headers=headers).json()==result['profile']
    assert client.patch('/v1/profile',headers=headers,json={'name':'Edited','department':'Teaching','id':'another'}).status_code==422
    assert client.patch('/v1/profile',headers=headers,json={'name':'Edited','department':'Teaching'}).json()['name']=='Edited'
    assert client.get('/v1/courses',headers=headers).json()==[]
    assert client.post('/v1/auth/logout',headers=headers).status_code==204
    assert client.get('/v1/me',headers=headers).status_code==401
    assert client.get('/v1/profile',headers=headers).status_code==401
