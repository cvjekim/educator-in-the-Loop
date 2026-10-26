import {afterEach,expect,it,vi} from 'vitest'
import {createClient} from './api'
afterEach(()=>vi.unstubAllGlobals())
it('서버의 stale 승인 오류를 숨기지 않는다',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:409,json:async()=>({code:'stale_review',message:'초안이 변경됐습니다.'})}))
  await expect(createClient('http://localhost:8000','test').review('run',1,'approve','')).rejects.toThrow('초안이 변경됐습니다.')
})
