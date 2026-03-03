import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'fs'
import path from 'path'

// Read DASHBOARD_PASSWORD from .env so the Vite proxy can authenticate with the API.
// Without this, the API's HTTP Basic Auth middleware rejects proxy requests with 401.
function readEnvPassword() {
  try {
    const envPath = path.resolve(__dirname, '../.env')
    const content = fs.readFileSync(envPath, 'utf-8')
    const match = content.match(/^DASHBOARD_PASSWORD=(.+)$/m)
    return match ? match[1].trim() : ''
  } catch {
    return ''
  }
}

const dashboardPassword = readEnvPassword()
const proxyHeaders = dashboardPassword
  ? { Authorization: 'Basic ' + Buffer.from(':' + dashboardPassword).toString('base64') }
  : {}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        headers: proxyHeaders,
      },
    },
  },
})
