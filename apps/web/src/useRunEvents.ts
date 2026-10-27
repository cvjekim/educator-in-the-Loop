import {useEffect,useState} from 'react'
import type {Client,Run} from './api'
import {StreamAccessError} from './runEvents'

export function useRunEvents(api:Client,courseId:string,onRuns:(runs:Run[])=>void){
  const [connectionError,setConnectionError]=useState('')
  useEffect(()=>{
    setConnectionError('')
    if(!courseId)return
    let disposed=false,denied=false,delay=1000,last=''
    let controller:AbortController|undefined,timer:ReturnType<typeof setTimeout>|undefined
    async function connect(){
      if(disposed||denied||document.visibilityState==='hidden')return
      const current=new AbortController();controller=current
      try{
        await api.subscribeRuns(courseId,current.signal,runs=>{
          if(disposed||current.signal.aborted)return
          delay=1000;setConnectionError('')
          const encoded=JSON.stringify(runs)
          if(encoded!==last){last=encoded;onRuns(runs)}
        })
      }catch(error){
        if(disposed||current.signal.aborted)return
        denied=error instanceof StreamAccessError
        setConnectionError(denied?'접근 권한이 변경됐습니다. 다시 로그인해 주세요.':'실시간 연결을 복구하고 있습니다. 연결되면 최신 상태를 표시합니다.')
        delay=Math.min(delay*2,30000)
      }
      if(!disposed&&!denied&&!current.signal.aborted)timer=setTimeout(connect,delay)
    }
    function visibility(){
      clearTimeout(timer);controller?.abort()
      if(document.visibilityState!=='hidden')void connect()
    }
    document.addEventListener('visibilitychange',visibility)
    void connect()
    return()=>{disposed=true;clearTimeout(timer);controller?.abort();document.removeEventListener('visibilitychange',visibility)}
  },[api,courseId,onRuns])
  return connectionError
}
