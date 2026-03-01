import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Use port 5174 so it doesn't clash with the main dashboard on 5173
  server: {
    port: 5174,
  },
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
