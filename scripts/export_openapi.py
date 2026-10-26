"""Generate the public API contract from FastAPI (no credentials or model calls)."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from apps.api.main import app

target=ROOT/'apps/web/public/openapi.json'
schema=json.dumps(app.openapi(),ensure_ascii=False,indent=2)+'\n'
if '--check' in sys.argv:
    if not target.exists() or target.read_text()!=schema:
        raise SystemExit('OpenAPI snapshot is stale; run scripts/export_openapi.py')
else:
    target.write_text(schema)
print('OpenAPI contract is current')
