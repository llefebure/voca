import { defineConfig } from '@playwright/test'

/**
 * Browser smoke suite. Requires the dev stack (`uv run task dev`) — supabase,
 * backend FastAPI on :8000, and the Next.js dev server on :3000. No webServer
 * directive: the stack is already the developer's environment.
 * Run it exclusively with `uv run task test:e2e` — the canonical path that
 * also exports the seeder's env (task-level dotenv, src/voca/.env); direct
 * `npx playwright test` runs are not supported.
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
