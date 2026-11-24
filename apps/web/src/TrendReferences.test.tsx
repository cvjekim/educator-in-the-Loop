import {render,screen} from '@testing-library/react'
import {expect,it} from 'vitest'
import TrendReferences from './TrendReferences'
it('shows search failures and distinguishes background from article body evidence',()=>{
 render(<TrendReferences draft={{trend_search:{query:'medical AI',searchedAt:'2026-11-24',providers:[{provider:'news',status:'error',count:0}]},trend_references:[{id:'S1',provider:'academic',title:'Paper',url:'https://doi.org/10.1/example',retrievedAt:'2026-11-24',evidenceType:'metadata'}]}}/>)
 expect(screen.getByText('뉴스 검색: 검색 실패 · 0건')).toBeInTheDocument()
 expect(screen.getByRole('link',{name:'[S1] Paper'})).toHaveAttribute('href','https://doi.org/10.1/example')
 expect(screen.getByText('제목·서지정보 확인 (본문 미확인)')).toBeInTheDocument()
})
