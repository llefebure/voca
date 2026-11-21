import { defineConfig } from '@playwright/test'

/**
 * Browser smoke suite. Requires the dev stack (`uv run task dev`) — supabase,
 * backend FastAPI on :8000, and the Next.js dev server on :3000. No webServer
 * directive: the stack is already the developer's environment.
 * Run with `uv run task test:e2e` (or `npx playwright test` in frontend/).
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  retries: 0,
  reporter: [['list']],
  outputDir: 'e2e/.results',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'setup',
      testMatch: /auth\.setup\.mjs/,
    },
    {
      name: 'smoke',
      testMatch: /smoke\.spec\.mjs/,
      use: { storageState: 'e2e/.auth/user.json' },
      dependencies: ['setup'],
    },
  ],
})
