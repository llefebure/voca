import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Seeds the E2E test user into the local Supabase stack: creates (or confirms)
 * the auth user and ensures `profiles` / `user_languages` rows exist, so the
 * signed-in smoke tests render a populated dashboard. Runs before the browser
 * (auth.setup.mjs), using the service-role key.
 *
 * Keys are read from the environment, else parsed out of the untracked
 * `src/voca/.env` — nothing secret is committed.
 */

export const TEST_EMAIL = 'e2e-test@voca.local'
export const TEST_PASSWORD = 'voca-e2e-password-1'

function readRepoEnvFile() {
  // Walk upward from this file (frontend/e2e/helpers/) until we find the
  // untracked src/voca/.env — handles the helper sitting any level deep.
  let dir = dirname(fileURLToPath(import.meta.url))
  for (let depth = 0; depth < 5; depth++) {
    try {
      return readFileSync(resolve(dir, 'src', 'voca', '.env'), 'utf8')
    } catch {
      dir = resolve(dir, '..')
    }
  }
  return ''
}

function envValue(name) {
  if (process.env[name]) return process.env[name]
  const match = readRepoEnvFile().match(new RegExp(`^${name}=(.*)$`, 'm'))
  return match ? match[1].trim() : undefined
}

function loadConfig() {
  const url = process.env.SUPABASE_URL ?? envValue('SUPABASE_URL') ?? 'http://127.0.0.1:54321'
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY ?? envValue('SUPABASE_SERVICE_ROLE_KEY')
  if (!serviceKey) {
    throw new Error(
      'E2E seeding needs SUPABASE_SERVICE_ROLE_KEY (set it or let Playwright read src/voca/.env). Is the Supabase stack up (`uv run task dev`)?',
    )
  }
  return { url: url.replace(/\/$/, ''), serviceKey }
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
