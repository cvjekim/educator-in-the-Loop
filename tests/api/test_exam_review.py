import copy
import pytest
from apps.api.exam_review import check_approval,prepare_edit,reviewed_questions,validate_counts,answer_key

def draft():
    return {'reviewSchemaVersion':1,'questions':[{'number':1,'question_type':'single_choice','content':'문제 보기','model_answer':'정답 비밀','learningObjective':'목표','bloomLevel':'understand','expectedDifficulty':'medium'}], 'rubrics':[{'question_number':1,'total_points':5,'criteria':[{'points':5,'description':'정확한 응답'}]}], 'itemReviews':{}}

def test_approval_requires_item_checks_and_reject_reason():
    d=draft()
    with pytest.raises(ValueError):check_approval(d)
    d['itemReviews']={'1':{'decision':'accept','checks':{k:True for k in ('alignment','cognitiveLevel','answerClarity','distractors','rubricClarity')}}}
    check_approval(d)
    assert '정답 비밀' in answer_key(d)
    d['itemReviews']['1']['decision']='reject'
    with pytest.raises(ValueError):check_approval(d)
    assert reviewed_questions(d)==[]

def test_edits_invalidate_stale_checks_and_preserve_metrics():
    old=draft();old['itemReviews']={'1':{'decision':'accept','reason':'정답 명확성 개선','checks':{'alignment':True}}}
    new=copy.deepcopy(old);new['questions'][0]['content']='수정된 문항'
    prepare_edit(old,new)
    assert new['itemReviews']['1']['decision']=='pending'
    assert new['reviewSummary']['modificationRate']==1
    with pytest.raises(ValueError):validate_counts(new['questions'],[{'question_type':'short_answer','count':1}])
    validate_counts(new['questions'],[{'question_type':'single_choice','count':1}])
