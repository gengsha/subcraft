import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  base: './',
  server: { port: 47654, strictPort: true },
  build: { outDir: 'dist', assetsInlineLimit: 0 },
})
