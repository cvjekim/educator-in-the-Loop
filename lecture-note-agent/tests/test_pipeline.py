"""
Tests for LangGraph pipeline state transitions.

Focus: interrupt before human_review, no progress past human_review without approval.
"""

import pytest
from unittest.mock import patch, MagicMock


INITIAL_STATE = {
    "subject": "machine-learning",
    "week": 3,
    "topic": "Logistic Regression",
    "guidelines": "",
    "current_stage": "guide_content",
    "overall_progress": 0,
    "status_message": "",
    "review_status": "pending",
    "raw_context": "",
    "draft_outline": None,
    "final_output": None,
}


class TestPipelineRouting:
    def test_does_not_reach_analysis_without_approval(self):
        """Pipeline must not advance past human_review when review_status != 'approved'."""
        from src.graph.pipeline import _should_continue

        state = {**INITIAL_STATE, "review_status": "pending"}
        result = _should_continue(state)
        assert result != "analysis_content"

    def test_routes_to_analysis_on_approval(self):
        from src.graph.pipeline import _should_continue

        state = {**INITIAL_STATE, "review_status": "approved"}
        result = _should_continue(state)
        assert result == "analysis_content"


def test_external_trends_are_intro_only_and_keep_sources(monkeypatch):
    import importlib
    module=importlib.import_module('src.graph.nodes.draft_content')
    observed={}
    def intro(trends,topic,guidelines):observed['intro']=trends;return 'Intro [S1]'
    def main(context,*args):observed['main']=context;return ['## Course only']
    monkeypatch.setattr(module,'_draft_intro',intro)
    monkeypatch.setattr(module,'_draft_main_outline',main)
    monkeypatch.setattr(module,'select_trends_for_topic',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Do not use shared local trends')))
    refs=[{'id':'S1','title':'External title','provider':'academic','summary':'External abstract','publishedAt':'2026-11-01','url':'https://doi.org/10.1/test','evidenceType':'abstract'}]
    result=module.draft_content({**INITIAL_STATE,'raw_context':'Private course evidence','external_trends':{'references':refs,'providers':[]}})
    assert observed['intro'][0]['summary']=='External abstract'
    assert observed['main']=='Private course evidence'
    assert result['draft_outline']['trend_references']==refs


def test_outline_preserves_explanation_and_approved_export(monkeypatch):
    import importlib
    draft=importlib.import_module('src.graph.nodes.draft_content')
    analysis=importlib.import_module('src.graph.nodes.analysis_content')
    text='## 표현 학습\n- 잠재 표현: 입력 특징을 벡터로 변환하는 방식\n  - 유사한 특징의 관계를 표현\n\n## 전이 학습\n- 기존 표현을 새 과제에 활용'
    slides=draft._split_slide_sections(text)
    assert len(slides)==2 and '잠재 표현' in slides[0]
    seen=[]
    monkeypatch.setattr(analysis,'_retrieve',lambda title,*args:('Course evidence','Course'))
    def bullets(title,passages,source,guidelines):
        seen.append((title,guidelines));return '- 상세 설명'
    monkeypatch.setattr(analysis,'_to_bullets',bullets)
    result=analysis.analysis_content({**INITIAL_STATE,'draft_outline':{'intro_slide':'Intro','main_slides':slides}})
    assert seen[0][0]=='## 표현 학습'
    assert '잠재 표현' in seen[0][1]
    assert result['final_output'].count('## 표현 학습')==1


def test_final_formatter_preserves_detailed_student_content(monkeypatch):
    import importlib
    module=importlib.import_module('src.graph.nodes.format_output')
    monkeypatch.setattr(module,'_get_llm',lambda: (_ for _ in ()).throw(AssertionError('Do not summarize detailed content')))
    content='## 개념\n\n### 정의\n- 특징 벡터는 각 관측치의 측정값을 순서가 있는 수치 배열로 표현\n\n```python\nx = [1, 2]\n```\n\n- 근거 [S1]'
    result=module.format_output({**INITIAL_STATE,'subject_name':'Synthetic course','final_output':content})
    assert content in result['final_output']
    assert 'Synthetic course' in result['final_output']
