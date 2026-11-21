import { expect, test } from '@playwright/test'

/**
 * Browser smoke test: visit every route signed in, assert its title renders and
 * that NOTHING throws. This catches the classes of UI breakage the jsdom suite
 * cannot see: hydration errors, runtime crashes on real Supabase data, broken
 * imports that typecheck misses.
 *
 * Needs the dev stack up (`uv run task dev` in another shell); the authenticated
 * state comes from the `setup` project (auth.setup.mjs).
 */

// Every route: [path, heading the page must show]. If you add a page, add it
// here — agents rely on this list to catch new-page breakage automatically.
const ROUTES = [
  ['/', 'Conversation Tutor'],
  ['/auth', 'Welcome Back'],
  ['/onboarding', 'Welcome to Voca'],
  ['/history', 'Session History'],
  ['/progress', 'Progress'],
  ['/library', 'Card Library'],
  ['/profile', 'My Profile'],
]

// Console noise that the dev stack legitimately produces but is not a UI bug:
// failed asset/backend fetches carry "Failed to load resource"; Next dev HMR
// and browser extensions add their own chatter here.
const CONSOLE_NOISE = [
  /failed to load resource/i,
  /net::/i,
  /favicon/i,
  /\[fast refresh\]/i,
  /third-party cookie/i,
  /websocket/i,
  /\b40[1349]\b/,
  /the play\(\) request was interrupted/i,
]

const isConsoleNoise = (text) => CONSOLE_NOISE.some((pattern) => pattern.test(text))

test.describe.configure({ mode: 'parallel' })

for (const [route, title] of ROUTES) {
  test(`route ${route} renders "${title}" without crashing`, async ({ page }) => {
    const pageErrors = []
    const consoleErrors = []
    page.on('pageerror', (error) => pageErrors.push(String(error)))
    page.on('console', (message) => {
      if (message.type() === 'error') consoleErrors.push(message.text())
    })

    const response = await page.goto(route, { waitUntil: 'load' })
    // The dev server must be up; a 5xx page render is a real failure.
    expect(response.status(), `GET ${route}`).toBeLessThan(500)

    // Signed-in routes redirect to /auth when signed out; the smoke project
    // carries the authenticated state, so the page's heading must appear.
    // `exact: true` stops the route announcer / empty-state copies (e.g. the
    // progress page's "No progress yet") from making this multi-match.
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible({
      timeout: 15_000,
    })

    // Give hydration and async loads a beat, then require: zero uncaught
    // exceptions, zero real console errors.
    await page.waitForTimeout(1_500)
    expect(pageErrors, `uncaught page errors on ${route}`).toEqual([])
    const realErrors = consoleErrors.filter((text) => !isConsoleNoise(text))
    expect(realErrors, `console errors on ${route}`).toEqual([])
  })
}
