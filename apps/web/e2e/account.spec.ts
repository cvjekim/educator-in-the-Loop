import {test,expect} from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

test('synthetic Google callback → registration → profile edit → logout',async({page})=>{
  let profile={id:'synthetic-user',name:'',department:''},revoked=false
  // Identity provider and HTTP transport are simulated here; DB isolation is tested separately.
  await page.route('https://accounts.google.com/gsi/client*',route=>route.fulfill({contentType:'application/javascript',body:`window.google={accounts:{id:{initialize(o){this.options=o},renderButton(el){const b=document.createElement('button');b.textContent='Google 계정으로 계속';b.onclick=()=>this.options.callback({credential:'synthetic-google-token'});el.append(b)},disableAutoSelect(){}}}};`}))
  await page.route('**/v1/**',async route=>{
    const path=new URL(route.request().url()).pathname,method=route.request().method()
    const headers={'Access-Control-Allow-Origin':'http://127.0.0.1:5173','Access-Control-Allow-Headers':'Authorization,Content-Type','Access-Control-Allow-Methods':'GET,POST,PATCH,OPTIONS'}
    if(method==='OPTIONS'){await route.fulfill({status:204,headers});return}
    let body:unknown={}
    if(path==='/v1/auth/config')body={googleClientId:'synthetic-client'}
    if(path==='/v1/auth/google'){
      const data=route.request().postDataJSON()
      if(!data.profile)body={needsRegistration:true}
      else{profile={...profile,...data.profile};body={needsRegistration:false,sessionToken:'synthetic-session',profile}}
    }
    if(path==='/v1/me')body={mode:'real',admin:false}
    if(path==='/v1/courses')body=[]
    if(path==='/v1/profile'){expect(route.request().headers().authorization).toBe('Bearer synthetic-session');profile={...profile,...route.request().postDataJSON()};body=profile}
    if(path==='/v1/auth/logout')revoked=true
    await route.fulfill({headers,contentType:'application/json',body:JSON.stringify(body)})
  })
  await page.goto('/')
  await page.getByRole('button',{name:'Google 계정으로 계속'}).click()
  await expect(page.getByRole('heading',{name:'회원정보 등록'})).toBeVisible()
  await expect(page.getByLabel('이름',{exact:true})).toBeFocused()
  await page.keyboard.type('Synthetic Professor');await page.keyboard.press('Tab');await page.keyboard.type('Synthetic Department')
  await page.getByRole('button',{name:'등록하고 시작하기'}).click()
  await page.getByRole('button',{name:'회원정보',exact:true}).click()
  await page.getByLabel('학과',{exact:true}).fill('Updated Department')
  await page.getByRole('button',{name:'변경사항 저장'}).click()
  await expect(page.getByRole('status')).toHaveText('회원정보를 저장했습니다.')
  expect((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze()).violations).toEqual([])
  for(const width of [360,768,1440]){
    await page.setViewportSize({width,height:1000})
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
  }
  await page.getByRole('button',{name:'강의 작업실로 돌아가기'}).click()
  await page.getByRole('button',{name:'로그아웃'}).click()
  await expect(page.getByRole('heading',{name:'교수자 로그인'})).toBeVisible()
  expect(revoked).toBeTruthy()
})
