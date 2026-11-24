import pytest
import nbformat
from apps.api.practice_notebook import generate_notebook

def test_sequential_teaching_cells_and_reference_context():
    observed=[]
    def model(messages):
        observed.extend(messages)
        return {'title':'합성 실습','objectives':['결측값: 식별','평균: 계산'],'summary':['입력: 합성값','출력: 평균'],
            'steps':[{'title':f'단계 {i}','concepts':['값: 관측치','평균: 합계 / 개수'],'procedure':['입력: 값 목록','연산: 합계'], 'code':f'value = {i}\nprint(value)', 'interpretation':['출력: 단계 번호','한계: 합성 예시']} for i in range(3)]}
    result=generate_notebook({'request':{'topic':'평균','guidelines':'반복문으로 평균 계산, Pandas 사용 제외'},'practiceReferences':'approved lecture marker'},model)
    nb=nbformat.from_dict(result['notebook']);nbformat.validate(nb)
    assert 'approved lecture marker' in observed[1][1]
    assert '반복문으로 평균 계산, Pandas 사용 제외' in observed[1][1]
    assert '## 수업 목표' in ''.join(nb.cells[0].source)
    assert [c.cell_type for c in nb.cells[1:]]==['markdown','code','markdown']*3
    assert result['execution']=='not_executed'
    assert all(c.execution_count is None and c.outputs==[] for c in nb.cells if c.cell_type=='code')


def test_code_fences_are_removed_without_running_code():
    from apps.api.practice_notebook import python_source
    assert python_source('```python\nprint(1)\n```')=='print(1)'
    with pytest.raises(SyntaxError):python_source('!pip install pandas')
    assert python_source('raise RuntimeError("never execute")').startswith('raise')


def test_invalid_python_has_one_bounded_repair():
    calls=[]
    def model(messages):
        calls.append(messages)
        return {'title':'연습','objectives':['목표1','목표2'],'summary':['요약1','요약2'],
            'steps':[{'title':'단계','concepts':['정의1','정의2'],'procedure':['절차1','절차2'],'code':'!pip install pandas' if len(calls)==1 else 'print(1)','interpretation':['점검1','점검2']} for _ in range(3)]}
    result=generate_notebook({'request':{'topic':'주제'}},model)
    assert len(calls)==2 and result['execution']=='not_executed'
    assert '문법 검사 실패' in calls[1][-1][1]


def test_export_preserves_markdown_and_rejects_empty_cells():
    import json
    from apps.api.practice_notebook import export_notebook
    notebook=nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell('# 목표\n- 개념: 정의'),nbformat.v4.new_code_cell('print(1)')])
    encoded=json.loads(nbformat.writes(notebook))
    output=json.loads(export_notebook(encoded))
    assert output['cells'][0]['source']=='# 목표\n- 개념: 정의'
    encoded['cells'][0]['source']=[]
    with pytest.raises(ValueError,match='Markdown'):export_notebook(encoded)
