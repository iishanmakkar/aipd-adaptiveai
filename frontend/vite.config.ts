import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // 'frontend' = this service's compose hostname: in-container proof traffic
    // (browser-agent, backend-container Playwright) arrives as Host: frontend
    // and Vite 5.4 403s unknown hosts. Browsers on a dev machine use localhost.
    allowedHosts: ['localhost', '127.0.0.1', '::1', 'frontend'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/v1': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  define: {
    'process.env': {},
  },
})