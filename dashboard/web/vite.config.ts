import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

const target = process.env.CS_API_URL || 'http://localhost:8000';
const token = process.env.CS_API_TOKEN;

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/v1': {
        target,
        changeOrigin: true,
        ws: true,
        headers: token ? { 'X-CS-Token': token } : {},
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
