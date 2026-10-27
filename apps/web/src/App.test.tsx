import {render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {describe,it,expect,vi} from 'vitest'
import App from './App'
import {createDemoClient} from './demo'

describe('교수자 작업 흐름',()=>{
  it('로그인 전에는 강의나 체험용 워크스페이스를 노출하지 않는다',()=>{
    render(<App/> )
    expect(screen.getByRole('heading',{name:'교수자 로그인'})).toBeInTheDocument()
    expect(screen.queryByText('01_머신러닝_기초.md')).not.toBeInTheDocument()
    expect(screen.queryByRole('button',{name:'시연 모드로 돌아가기'})).not.toBeInTheDocument()
  })
  it('인증 실패 시 로그인 화면을 유지하고 시연으로 전환하지 않는다',async()=>{
    const user=userEvent.setup()
    const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({message:'인증 실패'}),{status:401}))
    try{
      render(<App/>)
      await user.type(screen.getByLabelText('교수자 초대 토큰'),'invalid-token')
      await user.click(screen.getByRole('button',{name:'로그인'}))
      await screen.findByRole('alert')
      expect(screen.getByRole('heading',{name:'교수자 로그인'})).toBeInTheDocument()
      expect(screen.queryByRole('button',{name:'새 강의'})).not.toBeInTheDocument()
    }finally{fetch.mockRestore()}
  })
  it('로그아웃하면 작업 공간을 닫는다',async()=>{
    const user=userEvent.setup();render(<App initial={createDemoClient()}/>)
    await screen.findByText('01_머신러닝_기초.md')
    await user.click(screen.getByRole('button',{name:'로그아웃'}))
    expect(screen.getByRole('heading',{name:'교수자 로그인'})).toBeInTheDocument()
    expect(screen.queryByText('01_머신러닝_기초.md')).not.toBeInTheDocument()
  })
  it('승인 전 다운로드를 제공하지 않는다',async()=>{
    const user=userEvent.setup()
    render(<App initial={createDemoClient()}/>)
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
