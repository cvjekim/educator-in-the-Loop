import { copyFile, mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
const require = createRequire(import.meta.url)
const root = path.dirname(require.resolve('swagger-ui-dist/package.json'))
await mkdir('dist/swagger', { recursive: true })
for (const file of ['swagger-ui.css', 'swagger-ui-bundle.js']) await copyFile(path.join(root,file),path.join('dist/swagger',file))
