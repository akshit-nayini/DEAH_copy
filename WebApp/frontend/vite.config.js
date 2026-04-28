import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../backend/src/main/resources/static',
    emptyOutDir: true,
  },
  server: {
    port: 6005,
    host: '0.0.0.0',
    open: false,
    proxy: {
      '/api/v1/design': {
        target: 'http://localhost:8082',
        changeOrigin: true,
      },
      '/api/v1/requirements': {
        target: 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/v1/development': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    }
  },
  resolve: {
    extensions: ['.tsx', '.ts', '.jsx', '.js']
  }
})
