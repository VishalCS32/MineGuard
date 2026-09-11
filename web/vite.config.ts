import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  // `server` covers `npm run dev`; `preview` needs its own copy, since Vite
  // does not share proxy config between the two.
  preview: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    // The dashboard talks to the FastAPI backend; proxying keeps the browser
    // on one origin so there is no CORS dance in development.
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        configure: (proxy) => {
          proxy.on('error', () => {
            // Suppress noisy socket disconnects / ECONNABORTED in development
          });
        },
      },
    },
  },
});
