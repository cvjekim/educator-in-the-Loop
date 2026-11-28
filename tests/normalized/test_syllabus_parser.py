"""Synthetic syllabus fixtures: never include private course documents."""
import pytest
from apps.api.normalized.syllabus import parse_syllabus, render_syllabus
from apps.api.parse_document import parse

HEADER = ['주순', '기간', '학습주제', '학습내용', '학습목표']
ROWS = [HEADER, ['1', '03/01~03/07', '벡터', '성분과 연산', '벡터 표현'],
        ['2', '03/08~03/14', '행렬', '행렬 곱\n변환의 합성', '']]


def test_numbered_sections_are_not_weeks():
    result = parse_syllabus('''1. 교과목개요
개요 설명
2. 교육목표
1) 개념 이해
2) 원리 적용
3. 핵심역량 및 전공역량
분석 능력
4. 교재 및 참고문헌
주교재: Core Book
부교재: Reference Book
참고영상: Video
5. 수업방법
토론''')
    assert result == {'goals': '1) 개념 이해\n2) 원리 적용',
                      'mainTextbooks': 'Core Book', 'supplementaryTextbooks': 'Reference Book', 'weeks': []}


@pytest.mark.parametrize('separator', [' | ', '\t'])
def test_text_tables_share_pdf_mapping(separator):
    rows = [HEADER, ROWS[1], ['2', '03/08~03/14', '행렬', '행렬 곱', '']]
    text = '\n'.join(separator.join(row) for row in rows)
    assert parse_syllabus(text)['weeks'] == parse_syllabus('', [rows])['weeks']


def test_pdf_columns_override_flattened_text_and_preserve_wrapping():
    result = parse_syllabus('1. 교과목개요\n설명\n11. 수업계획\n1 벡터 성분과 연산', [ROWS])
    assert len(result['weeks']) == 2
    assert result['weeks'][0]['content'] == '성분과 연산'
    assert result['weeks'][1]['content'] == '행렬 곱\n변환의 합성'
    assert result['weeks'][1]['objectives'] == ''
    assert '03/' not in str(result)


def test_repeated_headers_and_continuation_rows():
    rows = [HEADER, ROWS[1], HEADER, ['', '', '', '내적', ''], ROWS[2]]
    assert parse_syllabus('', [rows])['weeks'][0]['content'] == '성분과 연산\n내적'


def test_markdown_and_plain_text_round_trip():
    plan = {'goals': '1) 원리 이해\n2) 실습 적용', 'mainTextbooks': 'Core', 'supplementaryTextbooks': 'Reference'}
    expected = {**plan, 'weeks': parse_syllabus('', [ROWS])['weeks']}
    text = render_syllabus(plan, expected['weeks'])
    assert parse_syllabus(text) == expected
    assert parse_syllabus('\n'.join(line.lstrip('# ') for line in text.splitlines())) == expected


def test_explicit_and_scoped_numbered_weeks():
    assert len(parse_syllabus('1. 개요\n2. 교육목표\n1) 원리')['weeks']) == 0
    result = parse_syllabus('## 주차별 계획\n| 1 | 벡터 | 성분 |\n2주차:행렬\n행렬 곱\n3. 미분\n변화율')
    assert [w['topic'] for w in result['weeks']] == ['벡터', '행렬', '미분']


def test_pdf_adapter_only_extracts_tables_for_syllabus(tmp_path, monkeypatch):
    import pdfplumber
    class Page:
        def extract_text(self): return '1. Overview\n11. Weekly plan'
        def extract_tables(self): return [ROWS]
    class PDF:
        pages = [Page()]
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(pdfplumber, 'open', lambda path: PDF())
    path = tmp_path / 'synthetic.pdf'
    path.write_bytes(b'%PDF-')
    assert 'tables' not in parse(path)
    result = parse(path, syllabus=True)
    assert len(parse_syllabus('\n'.join(result['pages']), result['tables'])['weeks']) == 2
