import {useEffect,useState} from 'react'
import type {Client} from './api'

export default function Invitations({api}:{api:Client}){
  const [items,setItems]=useState<{id:string;created_at:string;revoked:boolean}[]>([]),[token,setToken]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
  const refresh=async()=>setItems(await api.invitations())
  useEffect(()=>{void refresh().catch(()=>setError('초대 목록을 불러오지 못했습니다.'))},[api])
  async function action(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn();await refresh()}catch(e){setError(e instanceof Error?e.message:'초대를 처리하지 못했습니다.')}finally{setBusy(false)}}
  return <details className="panel"><summary>관리자 · 사용자 초대</summary><p>각 초대는 별도 작업 공간을 만듭니다. 발급된 토큰은 한 번만 표시됩니다.</p><button className="button secondary" disabled={busy} onClick={()=>void action(async()=>{setToken((await api.invite()).token)})}>새 초대 발급</button>{token&&<label>발급된 초대 토큰<input readOnly value={token} onFocus={e=>e.target.select()}/></label>}{error&&<p role="alert">{error}</p>}{items.map((item,i)=><div className="file-row" key={item.id}><span>초대 {i+1} · {new Date(item.created_at).toLocaleDateString()}</span><span>{item.revoked?'회수됨':'사용 가능'}</span>{!item.revoked&&<button className="text-button danger" disabled={busy} onClick={()=>{if(window.confirm('이 초대를 회수하면 해당 사용자가 접속할 수 없게 됩니다. 회수할까요?'))void action(async()=>{await api.revoke(item.id);setToken('')})}}>초대 회수</button>}</div>)}</details>
}
