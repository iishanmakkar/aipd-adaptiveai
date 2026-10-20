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
      // Inside the compose network `localhost` is this container itself, not
      // the backend: the container gets VITE_PROXY_TARGET=http://backend:8000
      // (see docker-compose.yml); plain `npm run dev` on a laptop keeps the
      // localhost default.
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
      '/v1': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})