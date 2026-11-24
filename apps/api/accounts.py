"""Google identity verification and private normalized account/session persistence."""
import hashlib
import hmac
import logging
import os
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.database.client import Database


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=120)
    department: str = Field(min_length=1, max_length=160)

    @field_validator('name', 'department')
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError('Enter a nonblank single-line value')
        return value


class GoogleInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    credential: str = Field(min_length=1, max_length=8192)
    nonce: str = Field(min_length=32, max_length=128)
    profile: ProfileInput | None = None


class Profile(ProfileInput):
    id: str


class LoginResult(BaseModel):
    needsRegistration: bool
    sessionToken: str | None = None
    profile: Profile | None = None


def reject(status, message):
    raise HTTPException(status, {'code': 'account_error', 'message': message})


def verify_google(credential, nonce, client_id):
    from google.oauth2.id_token import verify_oauth2_token
    from google.auth.transport.requests import Request
    from google.auth.exceptions import TransportError
    try:
        claims = verify_oauth2_token(credential, Request(), client_id)
    except TransportError:
        reject(503, 'Google 인증 서버에 연결하지 못했습니다. 다시 시도해 주세요.')
    except ValueError as error:
        # Never log the exception: audience/signature errors can contain credentials.
        reason = str(error).lower()
        category, message = 'invalid', 'Google 인증이 유효하지 않습니다. 다시 로그인해 주세요.'
        if 'token used too early' in reason:
            category, message = 'clockSkew', '서버 시간과 Google 인증 시간이 맞지 않습니다. 잠시 후 다시 로그인해 주세요.'
        elif 'token expired' in reason:
            category, message = 'expired', 'Google 인증이 만료되었습니다. 다시 로그인해 주세요.'
        elif 'audience' in reason:
            category, message = 'audienceMismatch', 'Google 로그인 설정이 일치하지 않습니다. 페이지를 새로고침한 후 다시 시도해 주세요.'
        logging.getLogger(__name__).warning('Google token verification failed: %s', category)
        reject(401, message)
    if (claims.get('iss') not in ('accounts.google.com', 'https://accounts.google.com')
            or not isinstance(claims.get('sub'), str) or not 1 <= len(claims['sub']) <= 255
            or not hmac.compare_digest(str(claims.get('nonce', '')), nonce)):
        reject(401, 'Google 인증 정보를 확인할 수 없습니다.')
    return claims['sub']


def profile_row(row):
    return {'id': str(row['id']), 'name': row['name'], 'department': row['department']}


class Accounts:
    def __init__(self, database):
        self.database = database

    def login(self, subject, profile=None):
        # A random provisional UUID has access to no existing user's rows.
        with self.database.transaction(uuid4()) as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ('google:'+subject,))
            db.execute("SELECT set_config('app.googleSubject',%s,true)", (subject,))
            account = db.execute('SELECT "userId" FROM "oauthAccounts" WHERE provider=\'google\' AND subject=%s', (subject,)).fetchone()
            if not account and profile is None:
                return {'needsRegistration': True}
            user_id = account['userId'] if account else uuid4()
            db.execute("SELECT set_config('app.userId',%s,true)", (str(user_id),))
            if not account:
                db.execute('INSERT INTO users (id,name,department) VALUES (%s,%s,%s)', (user_id,profile.name,profile.department))
                db.execute('INSERT INTO "oauthAccounts" ("userId",subject) VALUES (%s,%s)', (user_id,subject))
            row = db.execute('SELECT id,name,department,status FROM users WHERE id=%s', (user_id,)).fetchone()
            if not row or row['status'] != 'active':
                reject(403, '사용할 수 없는 계정입니다.')
            token = secrets.token_urlsafe(48)
            db.execute('INSERT INTO sessions ("userId","sessionTokenHash","expiresAt") VALUES (%s,%s,now()+interval \'12 hours\')',
                       (user_id,hashlib.sha256(token.encode()).hexdigest()))
            return {'needsRegistration':False,'sessionToken':token,'profile':profile_row(row)}

    def resolve(self, token):
        if not token or len(token) > 256:
            return None
        with self.database.transaction(uuid4()) as db:
            digest=hashlib.sha256(token.encode()).hexdigest()
            db.execute("SELECT set_config('app.sessionTokenHash',%s,true)",(digest,))
            session=db.execute('SELECT "userId" FROM sessions WHERE "sessionTokenHash"=%s AND "revokedAt" IS NULL AND "expiresAt">now()', (digest,)).fetchone()
            if not session:return None
            db.execute("SELECT set_config('app.userId',%s,true)",(str(session['userId']),))
            row=db.execute('SELECT id,name,department FROM users WHERE id=%s AND status=\'active\'',(session['userId'],)).fetchone()
            return profile_row(row) if row else None

    def update(self, user_id, profile):
        with self.database.transaction(user_id) as db:
            row=db.execute('UPDATE users SET name=%s,department=%s,"updatedAt"=now() WHERE id=%s AND status=\'active\' RETURNING id,name,department',
                           (profile.name,profile.department,user_id)).fetchone()
            if not row:reject(401,'다시 로그인해 주세요.')
            return profile_row(row)

    def logout(self, user_id, token):
        with self.database.transaction(user_id) as db:
            db.execute('UPDATE sessions SET "revokedAt"=now() WHERE "sessionTokenHash"=%s', (hashlib.sha256(token.encode()).hexdigest(),))


def install_accounts(app, database=None):
    dsn=os.getenv('DATABASE_URL')
    accounts=Accounts(database) if database else Accounts(Database(dsn, schema=os.getenv('DATABASE_SCHEMA','educator'))) if dsn and dsn.startswith(('postgres://','postgresql://')) else None
    app.state.accounts=accounts
    router=APIRouter(prefix='/v1',tags=['Google 로그인·회원정보'])
    bearer=HTTPBearer(auto_error=False)

    @router.get('/auth/config')
    def config():
        return {'googleClientId':os.getenv('GOOGLE_CLIENT_ID','') if accounts else ''}

    def current(credentials=Depends(bearer)):
        profile=accounts.resolve(credentials.credentials) if accounts and credentials else None
        if not profile:reject(401,'다시 로그인해 주세요.')
        return profile

    @router.post('/auth/google',response_model=LoginResult)
    def google(body:GoogleInput,response:Response):
        response.headers['Cache-Control']='no-store'
        client_id=os.getenv('GOOGLE_CLIENT_ID')
        if not accounts or not client_id:reject(503,'Google 로그인을 준비하고 있습니다. 잠시 후 다시 시도해 주세요.')
        subject=verify_google(body.credential,body.nonce,client_id)
        return accounts.login(subject,body.profile)

    @router.get('/profile',response_model=Profile)
    def get_profile(response:Response,profile=Depends(current)):
        response.headers['Cache-Control']='no-store'
        return profile

    @router.patch('/profile',response_model=Profile)
    def update_profile(body:ProfileInput,response:Response,profile=Depends(current)):
        response.headers['Cache-Control']='no-store'
        return accounts.update(profile['id'],body)

    @router.post('/auth/logout',status_code=204)
    def logout(profile=Depends(current),credentials=Depends(bearer)):
        accounts.logout(profile['id'],credentials.credentials)
        return Response(status_code=204,headers={'Cache-Control':'no-store'})

    app.include_router(router)
    return accounts
