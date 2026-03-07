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
    // host: true binds to 0.0.0.0 so the dashboard is reachable from other
    // devices on the same network via the host machine's LAN IP address.
    // e.g. http://192.168.1.42:5173 from another PC or phone on the same WiFi.
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        headers: proxyHeaders,
      },
    },
  },
})
