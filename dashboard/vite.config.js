import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import fs from 'fs'
import path from 'path'

// Read DASHBOARD_PASSWORD from .env so the Vite proxy can authenticate with the API.
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

// Read the API port written by start_all.py so the proxy targets the right port.
// Falls back to 8000 if the file doesn't exist (e.g. manual dev startup).
function readApiPort() {
  try {
    const portFile = path.resolve(__dirname, '../.api_port')
    const content = fs.readFileSync(portFile, 'utf-8').trim()
    const port = parseInt(content, 10)
    return isNaN(port) ? 8000 : port
  } catch {
    return 8000
  }
}

const dashboardPassword = readEnvPassword()
const apiPort = readApiPort()
const proxyHeaders = dashboardPassword
  ? { Authorization: 'Basic ' + Buffer.from(':' + dashboardPassword).toString('base64') }
  : {}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // host: true binds to 0.0.0.0 so the dashboard is reachable from other
    // devices on the same network via the host machine's LAN IP address.
    host: true,
    proxy: {
      '/api': {
        target: `http://localhost:${apiPort}`,
        changeOrigin: true,
        headers: proxyHeaders,
      },
    },
  },
})
