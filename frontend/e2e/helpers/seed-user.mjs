/**
 * Seeds the dev/E2E test user into the local Supabase stack: creates the auth
 * user, re-asserts its known password and confirmed email, and ensures
 * `profiles` / `user_languages` rows exist, so the login always works and the
 * signed-in smoke tests render a populated dashboard. Used by the E2E setup
 * (auth.setup.mjs) and by `uv run task dev` via scripts/ensure-dev-user.mjs,
 * using the service-role key.
 *
 * The seeder's keys are supplied by the `test:e2e` task (its dotenv loads the
 * untracked `src/voca/.env`; nothing secret is committed). That task is the
 * canonical — and only — supported way to run this suite; invoking `npx
 * playwright test` directly has no such env and fails fast below.
 */

export const TEST_EMAIL = 'e2e-test@voca.local'
export const TEST_PASSWORD = 'voca-e2e-password-1'

function loadConfig() {
  // Supplied by the test:e2e task's dotenv (src/voca/.env). Direct
  // `npx playwright test` invocations have no seeding env — run the suite
  // with `uv run task test:e2e` instead.
  const url = (process.env.SUPABASE_URL ?? 'http://127.0.0.1:54321').replace(/\/$/, '')
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY
  if (!serviceKey) {
    throw new Error(
      'E2E seeding has no SUPABASE_SERVICE_ROLE_KEY. Run the suite via its canonical path: `uv run task test:e2e` (the task exports the keys from src/voca/.env). Also check the stack is up: `uv run task dev`.',
    )
  }
  return { url, serviceKey }
}

export async function ensureUser() {
  const { url, serviceKey } = loadConfig()
  const serviceHeaders = {
    apikey: serviceKey,
    Authorization: `Bearer ${serviceKey}`,
    'Content-Type': 'application/json',
  }

  // Create the user; 422 just means it already exists.
  let userId
  const created = await fetch(`${url}/auth/v1/admin/users`, {
    method: 'POST',
    headers: serviceHeaders,
    body: JSON.stringify({ email: TEST_EMAIL, password: TEST_PASSWORD, email_confirm: true }),
  })
  if (created.ok) {
    userId = (await created.json()).id
  } else if (created.status === 422) {
    const list = await fetch(`${url}/auth/v1/admin/users?per_page=100`, {
      headers: serviceHeaders,
    })
    const { users } = await list.json()
    userId = (users ?? []).find((user) => user.email === TEST_EMAIL)?.id
  } else {
    throw new Error(`Could not seed the E2E user: ${created.status} ${await created.text()}`)
  }
  if (!userId) throw new Error(`Seeded user ${TEST_EMAIL} not found after create attempt`)

  // Re-assert the known password and confirmed email, so the login always
  // works — even when the account pre-existed with different credentials.
  const updated = await fetch(`${url}/auth/v1/admin/users/${userId}`, {
    method: 'PUT',
    headers: serviceHeaders,
    body: JSON.stringify({ password: TEST_PASSWORD, email_confirm: true }),
  })
  if (!updated.ok) throw new Error(`Could not re-assert the seeded user's password: ${updated.status} ${await updated.text()}`)

  // profiles row (target-language pointer) — upsert so re-seeds are harmless.
  const profile = await fetch(`${url}/rest/v1/profiles`, {
    method: 'POST',
    headers: { ...serviceHeaders, Prefer: 'resolution=merge-duplicates' },
    body: JSON.stringify({ id: userId, target_language: 'es' }),
  })
  if (!profile.ok) throw new Error(`Could not upsert the E2E profile: ${profile.status} ${await profile.text()}`)

  // One practiced-language row so the language switcher has something to show.
  const languageRow = await fetch(
    `${url}/rest/v1/user_languages`,
    {
      method: 'POST',
      headers: { ...serviceHeaders, Prefer: 'resolution=merge-duplicates,on_conflict=user_id,language' },
      body: JSON.stringify({ user_id: userId, language: 'es' }),
    },
  )
  if (!languageRow.ok) {
    throw new Error(`Could not upsert the E2E user_languages row: ${languageRow.status} ${await languageRow.text()}`)
  }

  return userId
}
