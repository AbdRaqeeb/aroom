import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The built app ships inside the Python package so installs need no Node.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const api = (globalThis as any).process?.env?.AROOM_API ?? 'http://127.0.0.1:4400'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': new URL('./src', import.meta.url).pathname } },
  build: {
    outDir: '../agentroom/assets/app',
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  server: {
    proxy: {
      '/api': api,
      '/login': api,
      '/logout': api,
    },
  },
})
