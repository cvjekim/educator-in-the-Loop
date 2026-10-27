import {afterEach,expect,it,vi} from 'vitest'
import {readRunEvents,StreamAccessError} from './runEvents'
afterEach(()=>vi.unstubAllGlobals())
it('parses fragmented SSE, ignores heartbeats and uses header authentication',async()=>{
  const bytes=new TextEncoder().encode(': keepalive\r\n\r\nevent: runs.snapshot\r\ndata: [{"topic":"강의"}]\r\n\r\nevent: stream.reconnect\n data: {}\n\n')
  const body=new ReadableStream({start(c){for(const byte of bytes)c.enqueue(new Uint8Array([byte]));c.close()}})
  const fetch=vi.fn().mockResolvedValue(new Response(body,{headers:{'Content-Type':'text/event-stream'}}));vi.stubGlobal('fetch',fetch)
  const update=vi.fn();await readRunEvents('https://api.example','secret','course',new AbortController().signal,update)
  expect(update).toHaveBeenCalledExactlyOnceWith([{topic:'강의'}])
  expect(fetch.mock.calls[0][0]).toBe('https://api.example/v1/courses/course/events')
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer secret')
})
it('treats revoked authentication as terminal',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('',{status:401})))
  await expect(readRunEvents('','secret','course',new AbortController().signal,vi.fn())).rejects.toBeInstanceOf(StreamAccessError)
})
