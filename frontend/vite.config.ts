import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const apiBaseUrl =
    loadEnv(mode, process.cwd(), '').VITE_API_BASE_URL?.trim()
    || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: apiBaseUrl
      ? {
          proxy: {
            '/api': {
              target: apiBaseUrl,
              changeOrigin: true,
              rewrite: (path) => path.replace(/^\/api/, ''),
            },
          },
        }
      : undefined,
  }
})
