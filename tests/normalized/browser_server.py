"""Local browser integration server. Synthetic identity allowed only in disposable test schema."""
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from urllib.parse import urlparse
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from dotenv import dotenv_values
import psycopg
from psycopg import sql
import uvicorn
from apps.database.migrate import apply
from apps.database.provision import provision_runtime
from apps.database.client import Database
from apps.api.normalized.files import Files
from apps.api.normalized.app import create_app
from apps.api import accounts

if __name__=='__main__':
    dsn=dotenv_values(ROOT/'.env.development')['DATABASE_URL']
    if urlparse(dsn).hostname not in ('127.0.0.1','localhost'):raise SystemExit('Local database only')
    schema='test_browser_'+uuid4().hex
    apply(dsn,schema);provision_runtime(dsn,schema)
    root=ROOT/'artifacts/tests'/schema
    os.environ.update(DATABASE_URL=dsn,DATABASE_URL_UNPOOLED=dsn,DATABASE_SCHEMA=schema,API_MODE='demo',RAG_MODE='keyword',
        GOOGLE_CLIENT_ID='synthetic-client',API_CORS_ORIGINS='http://127.0.0.1:5174',PRIVATE_STORAGE_ROOT=str(root))
    def verified(credential,nonce,client):
        if credential!='synthetic-browser-credential':raise ValueError('Unknown synthetic credential')
        return 'synthetic-browser-subject'
    accounts.verify_google=verified
    app=create_app(Database(dsn,schema),Files(root),mode='demo')
    worker=subprocess.Popen([sys.executable,'-m','apps.api.normalized.worker'],cwd=ROOT)
    try:uvicorn.run(app,host='127.0.0.1',port=8101,log_level='warning')
    finally:
        worker.terminate();worker.wait(timeout=15)
        with psycopg.connect(dsn,autocommit=True) as db:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
