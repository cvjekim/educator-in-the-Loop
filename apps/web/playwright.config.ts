import {defineConfig} from '@playwright/test'
export default defineConfig({
  testDir:'./e2e',fullyParallel:false,workers:1,timeout:60000,
  use:{baseURL:'http://127.0.0.1:5173',trace:'retain-on-failure'},
  reporter:[['list']],
  webServer:[
    {command:'npm run dev -- --port 5173 --strictPort',url:'http://127.0.0.1:5173',reuseExistingServer:!process.env.CI},
    {command:'../../.venv/bin/python -m uvicorn apps.api.main:app --app-dir ../.. --host 127.0.0.1 --port 8100',url:'http://127.0.0.1:8100/health',env:{API_DATABASE:'../../artifacts/e2e/service.sqlite3',API_MODE:'demo',API_ACCESS_TOKENS:'{"e2e-alice-token":"alice","e2e-bob-token":"bob"}',PYTHONDONTWRITEBYTECODE:'1'},reuseExistingServer:false},
    {command:'cd ../.. && .venv/bin/python -m apps.api.worker',wait:{stdout:/Educator worker ready/},env:{API_DATABASE:'artifacts/e2e/service.sqlite3',PYTHONDONTWRITEBYTECODE:'1'},reuseExistingServer:false},
  ],
})
