"""One agent per process; reuse legacy nodes without headless auto-approval.

Inputs and outputs are JSON. No user-supplied filesystem path is accepted.
"""
from contextlib import redirect_stdout
import importlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
DIRECTORIES = {'manager': 'manager-agent', 'lecture': 'lecture-note-agent', 'practice': 'practice-agent', 'exam': 'written-exam-agent', 'project': 'project-exam-agent'}


def demo(data):
    request = data['request']
    kind = request['task_type']
    title = request['topic']
    drafts = {
        'manager': {'tasks': [{'task_type': 'lecture', 'week': request['week'], 'subject': title, 'context': title}]},
        'lecture': {'intro_slide': '## 시연 안내\n- 합성 예시이며 최신 트렌드 검색은 실행하지 않았습니다.', 'main_slides': [f'## {title}\n- 학습 목표를 확인합니다.', '## 핵심 개념\n- 선택한 강의 자료의 근거를 검토합니다.']},
        'exam': {'questions': [{'number': 1, 'question_type': 'short_answer', 'content': f'{title}의 핵심 개념을 설명하시오.', 'model_answer': '시연용 예시 답안입니다.'}], 'rubrics': [{'question_number': 1, 'criteria': '개념의 정확성과 근거 제시 (시연)'}]},
        'project': {'evaluations': [{'student_id': r['student_id'], 'name': r['name'], 'summary': '시연: 실제 GitHub를 수집하지 않았습니다.', 'feedback_items': {'기여도': '교수자 검토가 필요한 합성 예시입니다.'}, 'overall_feedback': '시연용 평가 초안'} for r in request['roster']]},
        'practice': {'notebook': data.get('notebook'), 'execution': 'not_executed_demo'},
    }
    draft = drafts[kind]
    draft['notice'] = '합성 시연 데이터 · 실제 모델을 호출하지 않았습니다.'
    draft['guidelines'] = request.get('guidelines', '')
    if data['phase'] == 'finalize':
        draft = data['draft']
        output = json.dumps(draft['notebook'], ensure_ascii=False, indent=2) if kind == 'practice' else '# 합성 시연 결과\n\n```json\n' + json.dumps(draft, ensure_ascii=False, indent=2) + '\n```'
        return {'draft': draft, 'output': output}
    return {'draft': draft}


def run_real(data):
    request = data['request']
    kind = request['task_type']
    sys.path.insert(0, str(ROOT / DIRECTORIES[kind]))

    def node(name, state):
        fn = getattr(importlib.import_module('src.graph.nodes.' + name), name)
        state.update(fn(state))
        return state

    state = {'subject': 'uploaded-course', 'subject_name': 'uploaded-course', 'week': request['week'], 'topic': request['topic'],
             'guidelines': request['guidelines'], 'feedback': request['guidelines'], 'rubric_guidelines': request['rubric_guidelines'],
             'syllabus': data['syllabus'], 'raw_context': data['raw_context'], 'review_status': 'pending',
             'parameters': request['parameters'], 'roster': request['roster'], 'iteration_count': 0,
             'max_iterations': request['max_iterations']}
    finalize = data['phase'] == 'finalize'
    if finalize:
        # Only the authenticated API review transaction can queue this phase.
        state['review_status'] = 'approved'
        draft = data['draft']
        if kind == 'lecture':
            state['draft_outline'] = draft
            analysis = importlib.import_module('src.graph.nodes.analysis_content')
            analysis._web_search = lambda query: ''  # Course-only main content.
            node('analysis_content', state)
            node('format_output', state)
            output = state['final_output']
        elif kind == 'exam':
            fmt = importlib.import_module('src.graph.nodes.format_exam')
            output = fmt.build_question_paper('강의 시험', draft['questions']) + '\n\n---\n\n' + fmt.build_rubric_sheet('강의 시험', draft['questions'], draft['rubrics'])
        elif kind == 'project':
            fmt = importlib.import_module('src.graph.nodes.export_evaluation')
            output = '\n\n---\n\n'.join(fmt._render_report(d) for d in draft['evaluations'])
        elif kind == 'practice':
            output = json.dumps(draft['notebook'], ensure_ascii=False, indent=2)
        else:
            output = '# 승인된 학기 계획\n\n```json\n' + json.dumps(draft, ensure_ascii=False, indent=2) + '\n```'
        return {'draft': draft, 'output': output}

    if kind == 'manager':
        node('parse_course_plan', state)
        return {'draft': {'tasks': state['task_queue']}}
    if kind == 'lecture':
        if not data['raw_context'].strip():
            raise ValueError('source required')
        # An isolated temporary cwd has no local subjects or trends. No user's
        # private directory or unrelated global trend corpus is read.
        node('draft_content', state)
        return {'draft': state['draft_outline']}
    if kind == 'exam':
        generation = importlib.import_module('src.graph.nodes.generate_questions')
        generation.load_syllabus = lambda subject: data['syllabus']
        generation.load_materials = lambda subject: data['raw_context']
        if not data['raw_context'].strip():
            raise ValueError('source required')
        node('generate_questions', state)
        node('draft_rubric', state)
        if not state['questions'] or len(state['rubrics']) != len(state['questions']):
            raise ValueError('every question needs a rubric')
        return {'draft': {'questions': state['questions'], 'rubrics': state['rubrics']}}
    if kind == 'project':
        for name in ('init_rubric', 'crawl_github', 'summarize_project', 'evaluate_project'):
            node(name, state)
        return {'draft': {'evaluations': state['evaluation_drafts']}}
    import nbformat
    nb = nbformat.from_dict(data['notebook'])
    loader = importlib.import_module('src.notebook.loader')
    state['code_cells'], state['markdown_cells'] = loader.split_cells(nb)
    execution = 'not_executed'
    for _ in range(request['max_iterations']):
        node('revise_code', state)
        if not request['execute_notebook']:
            break
        reflection = importlib.import_module('src.graph.nodes.self_reflect')
        reflection._execute_cell = execute_sandbox
        node('self_reflect', state)
        execution = state['code_quality']
        if execution == 'pass':
            break
    node('format_markdown', state)
    cells = sorted(state['revised_cells'] + state['markdown_cells'], key=lambda c: c['index'])
    result = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(c['source']) if c['cell_type'] == 'code' else nbformat.v4.new_markdown_cell(c['source']) for c in cells])
    return {'draft': {'notebook': json.loads(nbformat.writes(result)), 'execution': execution, 'iterations': state['iteration_count']}}


def execute_sandbox(source):
    """Optional pre-pulled Docker image, no network, mounts, or host secrets."""
    image = os.environ['NOTEBOOK_SANDBOX_IMAGE']
    name = 'educator-cell-' + uuid4().hex
    try:
        proc = subprocess.run(['docker', 'run', '--pull=never', '--rm', '--name', name, '--network=none', '--memory=256m', '--cpus=1',
            '--pids-limit=64', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges', '--user=65534:65534',
            '--tmpfs=/tmp:rw,noexec,nosuid,size=32m', '-i', image, 'python', '-'], input=source, capture_output=True, text=True, timeout=30)
        return {'success': proc.returncode == 0, 'error': None if proc.returncode == 0 else 'ExecutionError', 'traceback': proc.stderr[-3000:], 'cell_index': None}
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'TimeoutExpired', 'traceback': None, 'cell_index': None}
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(1))
    try:
        data = json.load(sys.stdin)
        with tempfile.TemporaryDirectory(prefix='educator-agent-') as cwd, redirect_stdout(sys.stderr):
            os.chdir(cwd)
            result = demo(data) if data['mode'] == 'demo' else run_real(data)
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        print('Agent execution failed. Check model configuration and input.', file=sys.stderr)
        sys.exit(1)
