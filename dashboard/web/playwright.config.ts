import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './',
  testMatch: ['*.spec.ts'],
  timeout: 30000,
  webServer: {
    command: 'npm run dev',
    port: 5173,
    reuseExistingServer: true,
    timeout: 60000,
  },
  use: {
    baseURL: 'http://localhost:5173',
  },
});
