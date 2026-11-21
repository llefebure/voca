import { expect, test as setup } from '@playwright/test'
import { TEST_EMAIL, TEST_PASSWORD, ensureUser } from './helpers/seed-user.mjs'

/**
 * Signs the seeded E2E user in through the real /auth page, so the browser
 * storage (Supabase session) is exactly what a human session looks like. The
 * saved state is reused by the smoke project.
 */

const authFile = 'e2e/.auth/user.json'

setup('authenticate', async ({ page }) => {
  await ensureUser()
  await page.goto('/auth')
  await page.getByLabel('Email').fill(TEST_EMAIL)
  await page.getByLabel('Password').fill(TEST_PASSWORD)
  await page.getByRole('button', { name: 'Sign In' }).click()
  await expect(page.getByRole('heading', { name: 'Conversation Tutor' })).toBeVisible()
  await page.waitForTimeout(1_000) // let the dashboard settle
  await page.context().storageState({ path: authFile })
})
