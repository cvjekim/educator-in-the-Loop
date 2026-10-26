from pathlib import Path
import os
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('kind',['manager','lecture','exam','practice','project'])
def test_legacy_adapter_with_mocked_providers(kind):
    result=subprocess.run([sys.executable,str(ROOT/'tests/api/adapter_probe.py'),kind],capture_output=True,text=True,timeout=30,
                          env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHON_DOTENV_DISABLED':'1','LANGSMITH_TRACING':'false'})
    assert result.returncode==0,result.stderr
    assert 'adapter verified' in result.stdout
