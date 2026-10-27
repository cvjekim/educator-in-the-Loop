import {act,renderHook} from '@testing-library/react'
import {afterEach,expect,it,vi} from 'vitest'
import {createDemoClient} from './demo'
import type {Run} from './api'
import {useRunEvents} from './useRunEvents'
import {StreamAccessError} from './runEvents'
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks()})
it('one subscription stays idle without GET polling and pushes changes',async()=>{
  vi.useFakeTimers();const api=createDemoClient(),get=vi.spyOn(api,'runs'),update=vi.fn()
  let push!:(r:Run[])=>void;let signal!:AbortSignal
  vi.spyOn(api,'subscribeRuns').mockImplementation(async(_c,s,cb)=>{push=cb;signal=s;await new Promise<void>(r=>s.addEventListener('abort',()=>r(),{once:true}))})
  const {unmount}=renderHook(()=>useRunEvents(api,'course',update))
  await act(()=>vi.advanceTimersByTimeAsync(60000))
  expect(get).not.toHaveBeenCalled();expect(api.subscribeRuns).toHaveBeenCalledTimes(1)
  act(()=>push([{status:'waiting_review'} as Run]));expect(update).toHaveBeenCalledTimes(1)
  act(()=>push([{status:'waiting_review'} as Run]));expect(update).toHaveBeenCalledTimes(1)
  unmount();expect(signal.aborted).toBe(true)
})
it('aborts stale subscriptions on course change and pauses hidden tabs',async()=>{
  vi.useFakeTimers();const api=createDemoClient(),update=vi.fn();let visibility:DocumentVisibilityState='visible'
  vi.spyOn(document,'visibilityState','get').mockImplementation(()=>visibility)
  const subscriptions:{signal:AbortSignal;push:(runs:Run[])=>void}[]=[]
  vi.spyOn(api,'subscribeRuns').mockImplementation(async(_c,signal,push)=>{subscriptions.push({signal,push});await new Promise<void>(r=>signal.addEventListener('abort',()=>r(),{once:true}))})
  const {rerender,unmount}=renderHook(({course})=>useRunEvents(api,course,update),{initialProps:{course:'a'}})
  rerender({course:'b'});expect(subscriptions[0].signal.aborted).toBe(true)
  act(()=>subscriptions[0].push([]));expect(update).not.toHaveBeenCalled()
  visibility='hidden';act(()=>document.dispatchEvent(new Event('visibilitychange')));expect(subscriptions[1].signal.aborted).toBe(true)
  await act(()=>vi.advanceTimersByTimeAsync(60000));expect(subscriptions).toHaveLength(2)
  visibility='visible';act(()=>document.dispatchEvent(new Event('visibilitychange')));expect(subscriptions).toHaveLength(3);unmount()
})
it('reconnects broken streams but stops after access revocation',async()=>{
  vi.useFakeTimers();const api=createDemoClient(),update=vi.fn()
  const sub=vi.spyOn(api,'subscribeRuns').mockRejectedValueOnce(new Error('network')).mockRejectedValue(new StreamAccessError('denied'))
  const {unmount}=renderHook(()=>useRunEvents(api,'course',update))
  await act(()=>vi.advanceTimersByTimeAsync(30000));expect(sub).toHaveBeenCalledTimes(2);unmount()
})
