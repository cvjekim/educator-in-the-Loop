import {render,screen,fireEvent} from '@testing-library/react'
import {expect,it,vi} from 'vitest'
import ExamReview from './ExamReview'
it('records per-item rejection reason and marks unsaved changes',async()=>{
 const save=vi.fn().mockResolvedValue(undefined),dirty=vi.fn()
 render(<ExamReview busy={false} onDirty={dirty} onSave={save} draft={{questions:[{number:1,question_type:'short_answer',content:'문제',model_answer:'답'}],rubrics:[{question_number:1,criteria:[{points:1,description:'정확'}]}]}}/>)
 expect(screen.getByText('오답 매력도: 주관식 해당 없음')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('검토 결정'),{target:{value:'reject'}})
 fireEvent.change(screen.getByLabelText('수정·반려 사유'),{target:{value:'목표 범위 초과'}})
 fireEvent.click(screen.getByText('문항 검토 저장'))
 expect(save.mock.calls[0][0].itemReviews['1']).toMatchObject({decision:'reject',reason:'목표 범위 초과'})
 expect(dirty).toHaveBeenCalled()
})

it('renders structured model explanations and preserves them when saving',()=>{
 const save=vi.fn().mockResolvedValue(undefined)
 const explanations={'①':'표본 크기를 혼동한 선택지','②':['정답 근거',{detail:'중앙값과 평균의 차이'}]}
 render(<ExamReview busy={false} onDirty={vi.fn()} onSave={save} draft={{questions:[{number:1,question_type:'single_choice',content:'통계 문항',model_answer:'②',distractorRationale:explanations,evidence:[{source:'강의 자료',summary:'분포의 중심'}],cognitiveRationale:{level:'이해'},difficultyRationale:['기본 개념']}],rubrics:[]}}/>)
 expect(screen.getByText('표본 크기를 혼동한 선택지')).toBeTruthy()
 expect(screen.getByText('중앙값과 평균의 차이')).toBeTruthy()
 expect(screen.getByText('분포의 중심')).toBeTruthy()
 fireEvent.click(screen.getByText('문항 검토 저장'))
 expect(save.mock.calls[0][0].questions[0].distractorRationale).toEqual(explanations)
})
