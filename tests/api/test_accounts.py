import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from apps.api.accounts import ProfileInput, verify_google
from apps.api.main import create_app


def test_google_validation(monkeypatch):
    from google.oauth2 import id_token
    claims={'iss':'https://accounts.google.com','sub':'synthetic','nonce':'n'*32}
    def verify(token,request,audience):
        assert audience=='synthetic-client'
        return claims
    monkeypatch.setattr(id_token,'verify_oauth2_token',verify)
    assert verify_google('signed','n'*32,'synthetic-client')=='synthetic'
    with pytest.raises(HTTPException):verify_google('signed','x'*32,'synthetic-client')
    claims['iss']='https://attacker.invalid'
    with pytest.raises(HTTPException):verify_google('signed','n'*32,'synthetic-client')
    def invalid(*args):raise ValueError('expired or invalid audience/signature')
    monkeypatch.setattr(id_token,'verify_oauth2_token',invalid)
    with pytest.raises(HTTPException) as exc:verify_google('bad','n'*32,'synthetic-client')
    assert exc.value.status_code==401


def test_account_endpoints_fail_closed(tmp_path,monkeypatch):
    monkeypatch.delenv('DATABASE_URL',raising=False)
    app=create_app(str(tmp_path/'service.db'),tokens={'legacy':'instructor'})
    client=TestClient(app)
    assert client.get('/v1/auth/config').json()=={'googleClientId':''}
    assert client.post('/v1/auth/google',json={'credential':'x','nonce':'n'*32}).status_code==503
    for method,path,body in [('get','/v1/profile',None),('patch','/v1/profile',{'name':'A','department':'B'}),('post','/v1/auth/logout',None)]:
        assert getattr(client,method)(path,**({'json':body} if body else {}),headers={'Authorization':'Bearer legacy'}).status_code==401
    assert client.post('/v1/auth/google',json={'credential':'x','nonce':'n'*32,'profile':{'name':' ','department':'B'}}).status_code==422
    assert client.patch('/v1/profile',json={'name':'A','department':'B','id':'other'}).status_code in (401,422)


def test_profile_validation():
    assert ProfileInput(name=' A ',department=' B ').name=='A'
    for fields in [{'name':' ','department':'B'},{'name':'A','department':'\n'},{'name':'A','department':'B','role':'admin'}]:
        with pytest.raises(ValueError):ProfileInput(**fields)


@pytest.mark.parametrize('error,category,message', [
    ('Token used too early, private-data', 'clockSkew', '서버 시간'),
    ('Token expired, private-data', 'expired', '만료'),
    ('Token has wrong audience private-data', 'audienceMismatch', '설정이 일치'),
    ('Could not verify token signature. private-data', 'invalid', '유효하지'),
])
def test_google_failure_diagnostics_do_not_log_credentials(monkeypatch, caplog, error, category, message):
    from google.oauth2 import id_token
    def invalid(*args, **kwargs):
        raise ValueError(error)
    monkeypatch.setattr(id_token, 'verify_oauth2_token', invalid)
    with pytest.raises(HTTPException) as exc:
        verify_google('private-credential', 'n'*32, 'private-client')
    assert exc.value.status_code == 401
    assert message in exc.value.detail['message']
    assert category in caplog.text
    assert 'private-' not in caplog.text
