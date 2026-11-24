import {defineConfig} from '@playwright/test'
export default defineConfig({
 testDir:'./e2e-normalized',workers:1,timeout:90000,use:{baseURL:'http://127.0.0.1:5174',trace:'retain-on-failure'},reporter:[['list']],
 webServer:[
  {command:'npm run dev -- --port 5174 --strictPort',url:'http://127.0.0.1:5174',env:{VITE_API_URL:'http://127.0.0.1:8101',VITE_LEGACY_LOGIN:'false'},reuseExistingServer:false},
  {command:'../../.venv/bin/python ../../tests/normalized/browser_server.py',url:'http://127.0.0.1:8101/health',timeout:60000,reuseExistingServer:false}
 ]
})
