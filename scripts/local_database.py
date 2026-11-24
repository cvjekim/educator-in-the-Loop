"""Bootstrap a loopback-only development PostgreSQL cluster under ignored artifacts."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]

def main():
    from dotenv import dotenv_values
    import psycopg
    binary=Path(os.getenv('POSTGRES_BIN','/opt/homebrew/opt/postgresql@18/bin'))
    if not (binary/'initdb').is_file():
        found=shutil.which('initdb')
        if not found:raise SystemExit('Install PostgreSQL 18 and pgvector, or set POSTGRES_BIN')
        binary=Path(found).parent
    root=ROOT/'artifacts/development';root.mkdir(parents=True,exist_ok=True,mode=0o700)
    cluster=root/'postgres';password_file=root/'postgres-password'
    if not password_file.exists():password_file.write_text(secrets.token_urlsafe(36));password_file.chmod(0o600)
    password=password_file.read_text().strip()
    if not (cluster/'PG_VERSION').exists():
        subprocess.run([str(binary/'initdb'),'-D',str(cluster),'-U','educatorDevAdmin','--pwfile',str(password_file),'--auth=scram-sha-256','--encoding=UTF8','--locale=C'],check=True,stdout=subprocess.DEVNULL)
    if subprocess.run([str(binary/'pg_ctl'),'-D',str(cluster),'status'],capture_output=True).returncode:
        subprocess.run([str(binary/'pg_ctl'),'-D',str(cluster),'-l',str(root/'postgres.log'),'-o',f'-h 127.0.0.1 -p 55432 -k {root}','start'],check=True)
    base=f'postgresql://educatorDevAdmin:{quote(password)}@127.0.0.1:55432/'
    with psycopg.connect(base+'postgres',autocommit=True) as db:
        if not db.execute("SELECT 1 FROM pg_database WHERE datname='educator_development'").fetchone():db.execute('CREATE DATABASE educator_development')
    env_path=ROOT/'.env.development'
    env=dict(dotenv_values(env_path)) if env_path.exists() else {}
    env.update(DATABASE_URL=base+'educator_development',DATABASE_URL_UNPOOLED=base+'educator_development',DATABASE_SCHEMA='educatorDev',API_STORAGE='normalized')
    env_path.write_text('\n'.join(k+"='"+str(v).replace("'","\\'")+"'" for k,v in env.items() if v is not None)+'\n');env_path.chmod(0o600)
    print('Local database ready on 127.0.0.1:55432. Credentials saved only in ignored .env.development.')

if __name__=='__main__':main()
