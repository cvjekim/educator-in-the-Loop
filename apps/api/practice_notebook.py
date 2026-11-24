"""Build ordered teaching notebooks without executing model-produced code."""
import ast
import json
import re
from pathlib import Path
import nbformat
from pydantic import BaseModel, Field

class Step(BaseModel):
    title: str
    concepts: list[str] = Field(min_length=2)
    procedure: list[str] = Field(min_length=2)
    code: str
    interpretation: list[str] = Field(min_length=2)

class Plan(BaseModel):
    title: str
    objectives: list[str] = Field(min_length=2)
    summary: list[str] = Field(min_length=2)
    steps: list[Step] = Field(min_length=3, max_length=8)


def bullets(items):
    return '\n'.join('- '+item.strip().lstrip('- ').replace('\n', ' ') for item in items)


def python_source(source):
    source = source.strip()
    fenced = re.fullmatch(r'```(?:python|py)?\s*\n([\s\S]*?)\n```', source)
    if fenced:
        source = fenced.group(1)
    if re.search(r'<(?:dataset[^>]*|file_path|other_file_path)[^>]*>',source):
        raise SyntaxError('Unresolved input placeholder')
    if re.search(r'\b(?:os\.system|subprocess\.)',source):
        raise SyntaxError('Put environment setup in Markdown')
    tree = ast.parse(source)
    if not tree.body or all(isinstance(node, ast.Pass) for node in tree.body):
        raise SyntaxError('Empty exercise code')
    compile(source, '<notebook-cell>', 'exec')
    return source


def export_notebook(notebook):
    """Validate content before export; a valid JSON file can still be empty."""
    nb = nbformat.reads(json.dumps(notebook, ensure_ascii=False), as_version=4)
    nbformat.validate(nb)
    markdown = [cell for cell in nb.cells if cell.cell_type == 'markdown']
    if not markdown or any(not cell.source.strip() for cell in markdown):
        raise ValueError('Notebook Markdown content missing')
    if not any(cell.cell_type == 'code' and cell.source.strip() for cell in nb.cells):
        raise ValueError('Notebook code content missing')
    # Both list and string source are legal; normalize to strings for consumers.
    return json.dumps(nb, ensure_ascii=False, indent=2)


def assemble(plan):
    plan = Plan.model_validate(plan)
    cells = [nbformat.v4.new_markdown_cell(f'# {plan.title}\n\n## 수업 목표\n{bullets(plan.objectives)}\n\n## 실습 내용 요약\n{bullets(plan.summary)}\n\n- 실행 순서: 위에서 아래로 코드 셀 순차 실행\n- 실행 검증: 서버 자동 실행 미실시')]
    for i, step in enumerate(plan.steps, 1):
        code = python_source(step.code)  # Syntax only; never execute model code.
        cells.extend([
            nbformat.v4.new_markdown_cell(f'## {i}단계 · {step.title}\n\n### 핵심 개념\n{bullets(step.concepts)}\n\n### 실습 절차\n{bullets(step.procedure)}'),
            nbformat.v4.new_code_cell(code),
            nbformat.v4.new_markdown_cell(f'### 결과 해석·이해 점검\n{bullets(step.interpretation)}'),
        ])
    notebook = nbformat.v4.new_notebook(cells=cells, metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python'}})
    nbformat.validate(notebook)
    return {'notebook':json.loads(nbformat.writes(notebook)), 'execution':'not_executed', 'iterations':1}


def generate_notebook(data, invoke=None):
    if invoke is None:
        from langchain_openai import ChatOpenAI
        invoke = ChatOpenAI(model='gpt-4o-mini', temperature=0, timeout=120, max_retries=0).with_structured_output(Plan).invoke
    request=data['request']
    payload={key:request.get(key) for key in ('course_title','topic','week','guidelines')}
    payload.update(references=data.get('practiceReferences',''), sources=data.get('raw_context',''), syllabus=data.get('syllabus_context',''), existingNotebook=data.get('notebook'))
    prompt=Path(__file__).with_name('prompts').joinpath('practice_notebook.txt').read_text()
    messages=[('system',prompt),('human',json.dumps(payload,ensure_ascii=False))]
    plan=Plan.model_validate(invoke(messages))
    try:
        result = assemble(plan)
        result['reflection']={'validationType':'syntaxAndStructure','executionStatus':'notExecuted','repairCount':0}
        return result
    except SyntaxError as error:
        # A single bounded repair; never silently delete invalid code or execute it.
        repair='코드 셀 Python 문법 검사 실패. 모든 단계를 재작성. !pip/!kaggle/%magic/os.system/subprocess와 <dataset_identifier>/<file_path> 자리표시자 삭제. 설치는 Markdown 안내만. Kaggle 웹사이트에서 원하는 CSV 다운로드 후 Colab 업로드 흐름: from google.colab import files; uploaded = files.upload(); csv_names = [name for name in uploaded if name.lower().endswith(".csv")]; import io; import pandas as pd; df = pd.read_csv(io.BytesIO(uploaded[csv_names[0]])) 사용. CSV 없는 경우 명확한 ValueError. target 등 열 존재를 가정하지 말고 select_dtypes로 수치 열을 탐색. 사용자 입력과 업로드가 필요한 점을 명시. 합성 데이터 대체 금지. 모든 코드 셀에 유효한 Python 연산 제공. 환경 준비 셀은 import와 버전 확인, 마지막 점검 셀은 assert 등 실제 계산 결과 검사. # 없음 같은 주석 전용 코드 금지.'
        repair += f'\n검사 오류: {error.msg}; 행: {error.lineno}'
        result = assemble(invoke(messages+[('assistant',plan.model_dump_json()),('human',repair)]))
        result['iterations']=2
        result['reflection']={'validationType':'syntaxAndStructure','executionStatus':'notExecuted','repairCount':1,'errorType':'SyntaxError'}
        return result
