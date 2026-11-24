import {afterEach,expect,it,vi} from 'vitest'
import {normalizedClient} from './normalizedApi'
afterEach(()=>vi.unstubAllGlobals())
it('uploads large files in bounded authenticated chunks before completing',async()=>{
 const fetcher=vi.fn().mockImplementation(async(url:string)=>({ok:true,status:200,json:async()=>url.endsWith('document-uploads')?{id:'upload',chunkSize:3_000_000}:url.endsWith('complete')?{id:'doc',originalFileName:'notes.txt',byteSize:3_000_001,pages:1}:{}}))
 vi.stubGlobal('fetch',fetcher)
 const file=new File([new Uint8Array(3_000_001)],'notes.txt')
 const result=await normalizedClient('https://example.test','private-session').upload('course',file)
 expect(result.id).toBe('doc')
 expect(fetcher.mock.calls.map(c=>c[0])).toEqual(['https://example.test/v1/courses/course/document-uploads','https://example.test/v1/document-uploads/upload/parts/0','https://example.test/v1/document-uploads/upload/parts/1','https://example.test/v1/document-uploads/upload/complete'])
 for(const [,options] of fetcher.mock.calls)expect(options.headers.Authorization).toBe('Bearer private-session')
 expect((fetcher.mock.calls[1][1].body.get('file') as Blob).size).toBe(3_000_000)
 expect((fetcher.mock.calls[2][1].body.get('file') as Blob).size).toBe(1)
})
