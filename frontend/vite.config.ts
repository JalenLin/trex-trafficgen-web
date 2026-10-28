import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// In dev, the backend runs separately (python -m trex_gui); proxy API and WebSocket calls to it.
const backend = process.env.TREX_GUI_BACKEND ?? 'http://127.0.0.1:8080'

export default defineConfig({
  plugins: [vue()],
  // Relative asset paths keep the build usable when served from a subpath or loaded in a desktop shell.
  base: './',
  server: {
    proxy: {
      '/api': { target: backend, ws: true },
    },
  },
})
