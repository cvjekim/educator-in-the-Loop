"""Run actual legacy nodes in an isolated interpreter with mocked providers."""
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
os.environ['PYTHON_DOTENV_DISABLED']='1'
os.environ['OPENAI_API_KEY']='test-only'
kind=sys.argv[1]
calls=[]
questions=[{'number':1,'question_type':'short_answer','content':'개념을 설명하세요.','model_answer':'합성 답안'}]
rubrics=[{'question_number':1,'question_type':'short_answer','total_points':5,'criteria':[{'points':5,'description':'개념 정확성'}],'keywords':['개념']}]


class FakeLLM:
    def __init__(self,*args,**kwargs):
        pass
    def invoke(self,messages):
        calls.append(messages)
        if kind=='manager':
            text=json.dumps([{'task_type':'lecture','week':1,'subject':'합성 과목','context':'개념'}])
        elif kind=='exam':
            text=json.dumps(questions if len(calls)==1 else rubrics)
        elif kind=='project':
            text=json.dumps({'feedback_items':{'기여도':'합성 피드백'},'overall_feedback':'검토 필요'})
        elif kind=='practice':
            text='print(1)'
        else:
            text='## 합성 개념\n- 선택한 자료의 핵심을 설명합니다.'
        return SimpleNamespace(content=text)


def fake_get(url,**kwargs):
    value={'tree':[{'path':'README.md','type':'blob','size':10}]} if '/git/trees/' in url else {'encoding':'base64','content':base64.b64encode(b'synthetic project').decode()}
    return SimpleNamespace(json=lambda:value,raise_for_status=lambda:None)


with patch('langchain_openai.ChatOpenAI',FakeLLM),patch('requests.get',fake_get),tempfile.TemporaryDirectory() as cwd:
    from apps.api.legacy_runner import run_real
    from apps.api.models import RunCreate
    import nbformat
    request=RunCreate(task_type=kind,topic='개념',document_ids=['synthetic'],rubric_guidelines='기여도',roster=[{'student_id':'s1','name':'학생','github_id':'example','repo_name':'demo'}]).model_dump()
    data={'request':request,'syllabus':'1주차 개념','raw_context':'개념에 대한 합성 강의 자료입니다. '*100,'phase':'draft','notebook':json.loads(nbformat.writes(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell('print(1)')])))}
    os.chdir(cwd)
    draft=run_real(data)
    assert draft['draft'] and calls
    result=run_real({**data,'draft':draft['draft'],'phase':'finalize'})
    assert result['output']
    if kind=='practice':
        nbformat.validate(nbformat.from_dict(json.loads(result['output'])))
    print('adapter verified:',kind)
