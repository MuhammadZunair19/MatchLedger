import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: '../tests/e2e',
  fullyParallel: false,
  use: { baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000', trace: 'retain-on-failure' },
  reporter: 'list',
});
