import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Lets us write `@/components/...` instead of long relative paths.
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    port: 5173,
    // In development the frontend (5173) forwards /api calls to the backend (8000).
    proxy: { '/api': 'http://localhost:8000' },
    // The "How it works" screen shows docs/ASSUMPTIONS.md, which sits one folder up.
    fs: { allow: ['..'] },
  },
})
