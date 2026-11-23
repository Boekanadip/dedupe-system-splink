import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy keeps browser requests same-origin, so CORS is not involved in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/health': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
