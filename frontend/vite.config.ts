import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev: the FastAPI backend runs on :8000 (cd backend && .venv/bin/uvicorn app.main:app --port 8000).
// Build: `npm run build` -> dist/, served by the same FastAPI app inside the Databricks App.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
