import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { fileURLToPath } from 'url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Le backend FastAPI (Livewatch.py) tourne sur :8001 en local.
      // Toutes les routes /api, /ws, /proxy sont relayées vers lui en dev.
      '/api': { target: 'http://localhost:8001', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8001', ws: true },
      '/proxy': { target: 'http://localhost:8001', changeOrigin: true },
    },
  },
})
