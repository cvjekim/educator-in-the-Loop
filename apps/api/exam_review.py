"""Question-level HITL records remain in versioned draft JSON, not rubric tables."""
from collections import Counter

CHECKS=('alignment','cognitiveLevel','answerClarity','distractors','rubricClarity')
BLOOM=('remember','understand','apply','analyze','evaluate','create')

def validate_counts(questions,parameters):
    expected={p['question_type']:p['count'] for p in parameters}
    if Counter(q['question_type'] for q in questions)!=expected:
        raise ValueError('Generated question counts differ from request')
    numbers=[q['number'] for q in questions]
    if len(set(numbers))!=len(numbers):raise ValueError('Duplicate question number')


def reviewed_questions(draft):
    records=draft.get('itemReviews',{})
    return [q for q in draft['questions'] if records.get(str(q['number']),{}).get('decision')!='reject']


def check_approval(draft):
    if not draft.get('reviewSchemaVersion'):return
    records=draft.get('itemReviews',{})
    if not reviewed_questions(draft):raise ValueError('최소 한 문항을 채택하세요.')
    for q in draft['questions']:
        record=records.get(str(q['number']),{})
        if record.get('decision')=='reject':
            if not record.get('reason','').strip():raise ValueError('반려 사유를 입력하세요.')
            continue
        if record.get('decision')!='accept':raise ValueError('모든 문항을 검토한 뒤 채택 또는 반려하세요.')
        if not q.get('learningObjective','').strip() or q.get('bloomLevel') not in BLOOM:
            raise ValueError('채택 문항의 학습목표와 인지 수준을 확인하세요.')
        if q.get('expectedDifficulty') not in ('easy','medium','hard'):raise ValueError('예상 난이도를 확인하세요.')
        for key in CHECKS:
            if key=='distractors' and q['question_type']!='single_choice':continue
            if record.get('checks',{}).get(key) is not True:raise ValueError('채택 문항의 품질·루브릭 체크리스트를 모두 확인하세요.')


def prepare_edit(old,new):
    old_questions={q['number']:q for q in old['questions']}
    if set(old_questions)!={q['number'] for q in new['questions']} or len(new['questions'])!=len(old_questions):
        raise ValueError('문항 번호와 개수를 유지하고 제외할 문항은 반려로 표시하세요.')
    new['reviewSchemaVersion']=old.get('reviewSchemaVersion',1)
    records=new.get('itemReviews',{})
    if not isinstance(records,dict):raise ValueError('문항 검토 형식 오류')
    changed=set(old.get('reviewSummary',{}).get('editedNumbers',[]))
    old_r={r['question_number']:r for r in old['rubrics']}
    new_r={r['question_number']:r for r in new['rubrics']}
    if set(new_r)!=set(old_questions):raise ValueError('문항별 루브릭을 유지하세요.')
    for q in new['questions']:
        num=q['number'];record=records.get(str(num),{})
        if record.get('decision') in ('revise','reject') and not record.get('reason','').strip():raise ValueError('수정·반려 사유를 입력하세요.')
        if q!=old_questions[num] or new_r[num]!=old_r.get(num):
            if not record.get('reason','').strip():raise ValueError('내용이나 루브릭을 수정한 문항의 수정 사유를 입력하세요.')
            changed.add(num)
            if record==old.get('itemReviews',{}).get(str(num)):
                records[str(num)]={**record,'decision':'pending','checks':{}}
    new['itemReviews']=records
    rejected=[q['number'] for q in new['questions'] if records.get(str(q['number']),{}).get('decision')=='reject']
    new['reviewSummary']={'total':len(old_questions),'editedNumbers':sorted(changed),'editedCount':len(changed),'rejectedCount':len(rejected),'modificationRate':len(changed)/len(old_questions) if old_questions else 0}


def answer_key(draft):
    lines=['# 교수자용 정답·채점 루브릭','', '> 학생 배포용 문제지와 별도 보관','']
    rubrics={r['question_number']:r for r in draft['rubrics']}
    for q in reviewed_questions(draft):
        r=rubrics[q['number']]
        lines += [f"## 문항 {q['number']}",q['content'],'', '### 모범 답안',q['model_answer'],'',f"### 수행 수준 (총 {r.get('total_points',0)}점)"]
        lines += [f"- {c.get('points',0)}점: {c.get('description','')}" for c in r.get('criteria',[])]
        lines += ['',r.get('scoringGuidance',''),'']
    return '\n'.join(lines)


def review_report(revisions):
    lines=['# 문항별 교수자 검토 이력','', '- 수정률: 해당 생성 초안 이후 직접 편집된 문항 수 / 해당 버전 문항 수', '- 재생성된 초안은 별도 기준집합. 버전별 비율을 합쳐 학생 수나 독립 문항 수로 해석하지 않음.','']
    for revision in revisions:
        draft=revision['content'];summary=draft.get('reviewSummary',{})
        lines += [f"## 초안 v{revision['revisionNumber']} · {revision['origin']}",f"- 직접 수정: {summary.get('editedCount',0)} / {len(draft['questions'])}", '']
        for q in draft['questions']:
            r=draft.get('itemReviews',{}).get(str(q['number']),{})
            lines += [f"### 문항 {q['number']} · {q['question_type']}", f"- 결정: {r.get('decision','pending')}", f"- 사유: {r.get('reason','')}", f"- 인지 수준: {q.get('bloomLevel','미분류')}",f"- 예상 난이도: {q.get('expectedDifficulty','미분류')}",'']
    return '\n'.join(lines)
