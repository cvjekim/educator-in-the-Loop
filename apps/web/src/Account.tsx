import {useEffect,useRef,useState} from 'react'

export type Profile={id:string;name:string;department:string}
type ProfileFields=Pick<Profile,'name'|'department'>
export type AccountSession={token:string;profile:Profile}
type GoogleApi={initialize:(options:{client_id:string;nonce:string;ux_mode:'popup';callback:(result:{credential:string})=>void})=>void;renderButton:(element:HTMLElement,options:Record<string,unknown>)=>void;disableAutoSelect:()=>void}
declare global {interface Window {google?:{accounts:{id:GoogleApi}}}}

export async function accountRequest<T>(base:string,path:string,method='GET',body?:unknown,token?:string):Promise<T>{
  const response=await fetch(base.replace(/\/$/,'')+'/v1/'+path,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})},...(body?{body:JSON.stringify(body)}:{})})
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.message||'요청을 처리하지 못했습니다. 다시 시도해 주세요.')}
  return response.status===204?undefined as T:response.json()
}

let googleScript:Promise<void>|undefined
function loadGoogle(){
  if(window.google)return Promise.resolve()
  if(!googleScript)googleScript=new Promise<void>((resolve,reject)=>{
    const script=document.createElement('script');script.src='https://accounts.google.com/gsi/client?hl=ko';script.async=true
    script.onload=()=>resolve();script.onerror=()=>{googleScript=undefined;script.remove();reject(new Error('Google 로그인 화면을 불러오지 못했습니다. 페이지를 새로고침해 주세요.'))};document.head.append(script)
  })
  return googleScript
}

export function ProfileForm({initial,onSave,onCancel,registration=false}:{initial:ProfileFields;onSave:(fields:ProfileFields)=>Promise<void>;onCancel:()=>void;registration?:boolean}){
  const [name,setName]=useState(initial.name),[department,setDepartment]=useState(initial.department)
  const [busy,setBusy]=useState(false),[error,setError]=useState('')
  return <form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');try{await onSave({name:name.trim(),department:department.trim()})}catch(e){setError(e instanceof Error?e.message:'저장하지 못했습니다.')}finally{setBusy(false)}}}>
    <h1>{registration?'회원정보 등록':'회원정보 수정'}</h1>
    <p>{registration?'이름과 학과를 입력하면 나의 강의 작업 공간이 만들어집니다.':'강의 작업 공간에서 사용할 이름과 학과를 수정하세요.'}</p>
    <label>이름<input autoFocus required maxLength={120} autoComplete="name" value={name} onChange={e=>setName(e.target.value)}/></label>
    <label>학과<input required maxLength={160} autoComplete="organization-title" value={department} onChange={e=>setDepartment(e.target.value)}/></label>
    {error&&<p role="alert" className="dialog-error">{error}</p>}
    <div className="account-actions"><button className="button primary" disabled={busy||!name.trim()||!department.trim()}>{busy?'저장 중…':registration?'등록하고 시작하기':'변경사항 저장'}</button><button type="button" className="button" disabled={busy} onClick={onCancel}>취소</button></div>
  </form>
}

export function GoogleLogin({base,onLogin}:{base:string;onLogin:(session:AccountSession)=>Promise<void>}){
  const button=useRef<HTMLDivElement>(null),callback=useRef(onLogin);callback.current=onLogin
  const [pending,setPending]=useState<{credential:string;nonce:string}|null>(null)
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[ready,setReady]=useState(false)
  useEffect(()=>{
    let active=true
    async function login(credential:string,nonce:string){
      if(!active)return
      setBusy(true);setError('')
      try{
        const result=await accountRequest<{needsRegistration:boolean;sessionToken:string;profile:Profile}>(base,'auth/google','POST',{credential,nonce})
        if(!active)return
        if(result.needsRegistration)setPending({credential,nonce});else await callback.current({token:result.sessionToken,profile:result.profile})
      }catch(e){if(active)setError(e instanceof Error?e.message:'로그인하지 못했습니다.')}finally{if(active)setBusy(false)}
    }
    setReady(false);setError('')
    accountRequest<{googleClientId:string}>(base,'auth/config').then(async config=>{
      if(!active)return
      if(!config.googleClientId){setError('Google 로그인을 준비하고 있습니다.');return}
      await loadGoogle();if(!active||!button.current)return
      const nonce=crypto.randomUUID()+crypto.randomUUID()
      window.google!.accounts.id.initialize({client_id:config.googleClientId,nonce,ux_mode:'popup',callback:result=>void login(result.credential,nonce)})
      window.google!.accounts.id.renderButton(button.current,{type:'standard',theme:'outline',size:'large',text:'continue_with',locale:'ko'})
      setReady(true)
    }).catch(e=>{if(active)setError(e.message)})
    return()=>{active=false}
  },[base])
  return <section aria-label="Google 로그인" aria-busy={busy}>
    <div ref={button} hidden={!!pending||busy}/>
    {!ready&&!error&&<p role="status">로그인을 준비하고 있습니다…</p>}
    {busy&&<p role="status">로그인 확인 중…</p>}
    {error&&<p role="alert" className="dialog-error">{error}</p>}
    {pending&&<ProfileForm registration initial={{name:'',department:''}} onCancel={()=>setPending(null)} onSave={async profile=>{
      const result=await accountRequest<{sessionToken:string;profile:Profile}>(base,'auth/google','POST',{...pending,profile})
      await callback.current({token:result.sessionToken,profile:result.profile});setPending(null)
    }}/>}
  </section>
}

export function AccountPage({base,session,onSaved,onBack}:{base:string;session:AccountSession;onSaved:(profile:Profile)=>void;onBack:()=>void}){
  const [saved,setSaved]=useState(false)
  return <div className="login-shell"><main className="panel login-panel"><p className="eyebrow">나의 계정 · GOOGLE</p>
    <ProfileForm initial={session.profile} onCancel={onBack} onSave={async fields=>{setSaved(false);const profile=await accountRequest<Profile>(base,'profile','PATCH',fields,session.token);onSaved(profile);setSaved(true)}}/>
    {saved&&<p role="status">회원정보를 저장했습니다.</p>}
    <button className="button" onClick={onBack}>강의 작업실로 돌아가기</button>
  </main></div>
}
