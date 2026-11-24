import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
const loginHeaders={'Cross-Origin-Opener-Policy':'same-origin-allow-popups','Referrer-Policy':'strict-origin-when-cross-origin'}
export default defineConfig({plugins:[react()],server:{headers:loginHeaders},preview:{headers:loginHeaders},test:{environment:'jsdom',setupFiles:['./src/test-setup.ts'],exclude:['e2e/**','e2e-normalized/**','node_modules/**']}})
