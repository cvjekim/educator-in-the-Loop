import {render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {describe,it,expect} from 'vitest'
import App from './App'
import {createDemoClient} from './demo'

describe('교수자 작업 흐름',()=>{
  it('합성 시연임을 표시하고 승인 전 다운로드를 제공하지 않는다',async()=>{
    const user=userEvent.setup()
    render(<App initial={createDemoClient()}/>)
    expect(screen.getByText(/합성 데이터로 흐름을 체험/)).toBeInTheDocument()
    await screen.findByText('01_머신러닝_기초.md')
    await user.type(screen.getByLabelText('이번 주 주제'),'지도학습')
    await user.click(screen.getByRole('button',{name:'초안 만들기'}))
    await screen.findByRole('button',{name:'v1 승인'})
    expect(screen.queryByRole('button',{name:'결과 다운로드'})).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('수정 요청'),'예시를 추가해 주세요')
    await user.click(screen.getByRole('button',{name:'수정 요청'}))
    await screen.findByRole('button',{name:'v2 승인'})
    await user.click(screen.getByRole('button',{name:'v2 승인'}))
    await screen.findByRole('button',{name:'결과 다운로드'})
    expect(screen.getByText('교수자 승인 완료')).toBeInTheDocument()
  })
  it('강의를 만들면 선택된 강의의 자료가 초기화된다',async()=>{
    const user=userEvent.setup();render(<App initial={createDemoClient()}/>)
    await screen.findByText('01_머신러닝_기초.md')
    await user.click(screen.getByRole('button',{name:'새 강의'}))
    await user.type(screen.getByLabelText('강의 이름'),'새로운 강의')
    await user.click(screen.getByRole('button',{name:'강의 만들기'}))
    await waitFor(()=>expect(screen.getByLabelText('현재 강의')).toHaveDisplayValue('새로운 강의'))
    expect(screen.queryByText('01_머신러닝_기초.md')).not.toBeInTheDocument()
  })
})
