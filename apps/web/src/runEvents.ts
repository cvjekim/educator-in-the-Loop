import type {Run} from './api'
export class StreamAccessError extends Error {}

// fetch streaming keeps bearer credentials in headers, never in URLs or storage.
export async function readRunEvents(base:string,token:string,course:string,signal:AbortSignal,onRuns:(runs:Run[])=>void){
  const response=await fetch(`${base.replace(/\/$/,'')}/v1/courses/${course}/events`,{headers:{Authorization:`Bearer ${token}`,Accept:'text/event-stream'},signal,cache:'no-store'})
  if([401,403,404].includes(response.status))throw new StreamAccessError('실시간 연결 권한이 없습니다. 다시 로그인해 주세요.')
  if(!response.ok||!response.body||!response.headers.get('content-type')?.includes('text/event-stream'))throw new Error('실시간 서버에 연결할 수 없습니다.')
  const reader=response.body.getReader(),decoder=new TextDecoder()
  let buffer=''
  try{
    while(!signal.aborted){
      const {done,value}=await reader.read()
      if(done)return
      buffer+=decoder.decode(value,{stream:true})
      if(buffer.length>20_000_000)throw new Error('실시간 응답 크기를 초과했습니다.')
      let match:RegExpExecArray|null
      while((match=/\r?\n\r?\n/.exec(buffer))){
        const block=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length)
        let event='message';const data:string[]=[]
        for(const line of block.split(/\r?\n/)){
          if(line.startsWith('event:'))event=line.slice(6).trim()
          if(line.startsWith('data:'))data.push(line.slice(5).trimStart())
        }
        if(event==='stream.denied')throw new StreamAccessError('접근 권한이 변경됐습니다. 다시 로그인해 주세요.')
        if(event==='stream.error')throw new Error('실시간 연결이 끊겼습니다.')
        if(event==='stream.reconnect')return
        if(event==='runs.snapshot'){
          const runs:unknown=JSON.parse(data.join('\n'))
          if(!Array.isArray(runs))throw new Error('잘못된 실시간 응답입니다.')
          onRuns(runs as Run[])
        }
      }
    }
  }finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
}
