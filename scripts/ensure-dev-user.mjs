#!/usr/bin/env node
/**
 * Ensures the dev test user exists and its login works, so `uv run task dev`
 * always leaves a ready-to-use test sign-in behind. Reuses the E2E seeder
 * (frontend/e2e/helpers/seed-user.mjs) so dev startup and the browser tests
 * share exactly one identity.
 *
 * Env comes from the task's dotenv (src/voca/.env), same mechanism as
 * `test:e2e`: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY, which resolve per
 * worktree in stack mode.
 */
import { TEST_EMAIL, TEST_PASSWORD, ensureUser } from '../frontend/e2e/helpers/seed-user.mjs'

try {
  await ensureUser()
  console.log(`Dev test user ready — sign in at /auth as ${TEST_EMAIL} / ${TEST_PASSWORD}`)
} catch (err) {
  console.error(`Could not ensure the dev test user login: ${err?.message ?? err}`)
  console.error('Is the local Supabase stack up (`uv run task supabase-ready`) and is src/voca/.env complete?')
  process.exit(1)
}
