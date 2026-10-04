import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 9981,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/sources': 'http://127.0.0.1:8000',
      '/sites': 'http://127.0.0.1:8000',
      '/configs': 'http://127.0.0.1:8000',
      '/import': 'http://127.0.0.1:8000'
    }
  },
  build: { outDir: 'dist', chunkSizeWarningLimit: 1500 }
})
