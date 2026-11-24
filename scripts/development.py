"""Run the private normalized development prototype; never deploy or mutate production schema."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env.development',override=True)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['migrate','api','worker','web'])
    args=parser.parse_args()
    schema=os.getenv('DATABASE_SCHEMA','educatorDev')
    from urllib.parse import urlparse
    if urlparse(os.getenv('DATABASE_URL','')).hostname not in ('127.0.0.1','localhost','::1'):
        raise SystemExit('Development requires a local PostgreSQL host')
    if schema!='educatorDev' or os.getenv('VERCEL'):raise SystemExit('Use educatorDev locally; production is not allowed')
    os.environ.update(API_STORAGE='normalized',DATABASE_SCHEMA=schema)
    os.environ.setdefault('PRIVATE_STORAGE_ROOT',str(ROOT/'artifacts/development/files'))
    if args.command=='migrate':
        from apps.database.migrate import apply
        from apps.database.provision import provision_runtime
        dsn=os.getenv('DATABASE_URL_UNPOOLED') or os.environ['DATABASE_URL']
        print(apply(dsn,schema));print(provision_runtime(dsn,schema))
        return
    if args.command=='api':command=[sys.executable,'-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port','8000']
    elif args.command=='worker':command=[sys.executable,'-m','apps.api.normalized.worker']
    else:
        os.environ['VITE_API_URL']='http://127.0.0.1:8000'
        os.environ['VITE_LEGACY_LOGIN']='false'
        command=['npm','--prefix',str(ROOT/'apps/web'),'run','dev','--','--port','5173']
    raise SystemExit(subprocess.call(command,cwd=ROOT))

if __name__=='__main__':main()
