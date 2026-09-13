/// <reference types="vitest/config" />
import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// The legal-assistant API (FastAPI, app/main.py). In dev, Vite proxies /api/*
// to it so the browser needs no CORS setup or hard-coded host; in production
// FastAPI serves this build at /legal/ and the API is same-origin
// (see src/state/connection.ts). scripts/legal-web.sh sets LEGAL_API.
const API = process.env.LEGAL_API ?? 'http://127.0.0.1:8000'

export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/legal/' : '/',
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    proxy: {
      '/api': { target: API, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        advancedChunks: {
          groups: [
            { name: 'charts', test: /node_modules[\\/](recharts|d3-|victory)/ },
            { name: 'motion', test: /node_modules[\\/](framer-motion|motion-)/ },
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
          ],
        },
      },
    },
  },
  test: { environment: 'node', include: ['src/**/*.test.ts'] },
}))
