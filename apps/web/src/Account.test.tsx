import {render,screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {describe,it,expect,vi} from 'vitest'
import {ProfileForm,AccountPage} from './Account'

describe('회원정보',()=>{
  it('등록에는 이름과 학과만 받고 빈 값은 제출하지 않는다',async()=>{
    const user=userEvent.setup(),save=vi.fn().mockResolvedValue(undefined)
    render(<ProfileForm registration initial={{name:'',department:''}} onSave={save} onCancel={()=>{}}/>)
    expect(screen.getByRole('button',{name:'등록하고 시작하기'})).toBeDisabled()
    await user.type(screen.getByLabelText('이름'),' 교수자 ');await user.type(screen.getByLabelText('학과'),' 교육학과 ')
    await user.click(screen.getByRole('button',{name:'등록하고 시작하기'}))
    expect(save).toHaveBeenCalledWith({name:'교수자',department:'교육학과'})
  })
  it('실패하면 입력을 보존하고 다시 저장할 수 있다',async()=>{
    const user=userEvent.setup(),save=vi.fn().mockRejectedValueOnce(new Error('연결 실패')).mockResolvedValue(undefined)
    render(<ProfileForm initial={{name:'교수자',department:'학과'}} onSave={save} onCancel={()=>{}}/>)
    await user.click(screen.getByRole('button',{name:'변경사항 저장'}));expect(await screen.findByRole('alert')).toHaveTextContent('연결 실패')
    expect(screen.getByLabelText('이름')).toHaveValue('교수자');await user.click(screen.getByRole('button',{name:'변경사항 저장'}));expect(save).toHaveBeenCalledTimes(2)
  })
  it('수정 요청은 로그인 세션을 사용하고 저장 완료를 알린다',async()=>{
    const user=userEvent.setup(),saved=vi.fn(),profile={id:'synthetic',name:'교수자',department:'학과'}
    const fetch=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify(profile)))
    try{
      render(<AccountPage base="https://api.example" session={{token:'synthetic-token',profile}} onSaved={saved} onBack={()=>{}}/>)
      await user.click(screen.getByRole('button',{name:'변경사항 저장'}))
      expect(await screen.findByRole('status')).toHaveTextContent('회원정보를 저장했습니다.')
      expect(fetch).toHaveBeenCalledWith('https://api.example/v1/profile',expect.objectContaining({method:'PATCH',headers:expect.objectContaining({Authorization:'Bearer synthetic-token'})}))
      expect(saved).toHaveBeenCalledWith(profile)
    }finally{fetch.mockRestore()}
  })
})
