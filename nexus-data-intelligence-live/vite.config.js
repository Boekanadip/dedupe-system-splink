import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy keeps browser requests same-origin, so CORS is not involved in dev.
export default defineConfig(({ mode }) => {
  const rootEnv = loadEnv(mode, '..', '')
  const apiKey = rootEnv.DEDUP_API_KEY || ''
  const proxyHeaders = apiKey ? { 'x-api-key': apiKey } : {}

  return {
    plugins: [react()],
    server: {
      port: 5174,
      proxy: {
        '/api': { target: 'http://localhost:8000', changeOrigin: true, headers: proxyHeaders },
        '/health': { target: 'http://localhost:8000', changeOrigin: true, headers: proxyHeaders },
      },
    },
  }
})
