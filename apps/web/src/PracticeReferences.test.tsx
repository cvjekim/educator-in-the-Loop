import {render,screen,fireEvent} from '@testing-library/react'
import {expect,it,vi} from 'vitest'
import PracticeReferences from './PracticeReferences'
import EducationReview from './EducationReview'
import type {NormalClient} from './normalizedApi'
it('shows draft/material versions separately and selects exact reference',async()=>{
 const api={practiceReferences:vi.fn().mockResolvedValue([{kind:'draft',id:'revision-1',title:'Classification',weekNumber:1,version:2,label:'강의 초안 (사실 검증 필요)'},{kind:'material',id:'material-1',title:'Classification',weekNumber:1,version:1,label:'생성된 강의자료'}])} as unknown as NormalClient
 const change=vi.fn()
 render(<PracticeReferences api={api} courseId="course" revision={1} selected={[]} onChange={change}/>)
 const boxes=await screen.findAllByRole('checkbox');expect(boxes).toHaveLength(2)
 fireEvent.click(boxes[0]);expect(change).toHaveBeenCalledWith([{kind:'draft',id:'revision-1'}])
 expect(screen.getByText('생성된 강의자료 · v1')).toBeInTheDocument()
})
it('does not label a failed review as passed',()=>{
 render(<EducationReview report={{status:'reviewFailed',message:'검토를 완료하지 못했습니다.'}}/>)
 expect(screen.getByText('자동 검토 실패')).toBeInTheDocument()
 expect(screen.queryByText('자동 기준 충족 · 교수자 확인 필요')).not.toBeInTheDocument()
})
