import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SupabaseMockOptions } from './helpers/supabase-mock'

/**
 * The onboarding wizard's write contract: the profiles row always exists (the
 * on_auth_user_created trigger creates it at signup), so the wizard *updates*
 * it — stamping the target-language pointer + onboarded_at with a
 * `.select('id')` confirmation — and writes the learner context only into
 * user_languages. No profiles upsert, no level/goals/interests copies.
 */

// Read lazily by the supabase mock (functions in TableConfig resolve at query
// time) — same hoisted-ref pattern as language-context.test.
const seed = vi.hoisted(() => {
  const seedRef = {
    profilesWriteError: null as { message: string } | null,
    tables: undefined as unknown as SupabaseMockOptions['tables'],
  }
  seedRef.tables = {
    profiles: {
      maybeSingle: { id: 'test-user', target_language: 'es', onboarded_at: null },
      writeError: () => seedRef.profilesWriteError,
    },
  }
  return seedRef
})

vi.mock('@/lib/supabase', async () => {
  const { createSupabaseMock } = await import('./helpers/supabase-mock')
  return {
    supabase: createSupabaseMock({ tables: seed.tables as never }),
  }
})

vi.mock('next/navigation', async () => {
  const { createNavigationMock } = await import('./helpers/test-navigation')
  return createNavigationMock('/onboarding')
})

import OnboardingPage from '@/app/onboarding/page'
import { supabase } from '@/lib/supabase'
import type { SupabaseMock } from './helpers/supabase-mock'

const supabaseMock = supabase as unknown as SupabaseMock

/** Hit "Complete Setup" on the goals step (arrive there first via Continue). */
function completeSetup() {
  fireEvent.click(screen.getByRole('button', { name: /complete setup/i }))
}

beforeEach(() => {
  cleanup()
  seed.profilesWriteError = null
  supabaseMock.chains.length = 0
  supabaseMock.writes.length = 0
  supabaseMock.setUser({ id: 'test-user' })
})

afterEach(() => {
  cleanup()
})

describe('Onboarding writes', () => {
  it('updates profiles (pointer + stamp) and upserts the user_languages context', async () => {
    render(<OnboardingPage />)
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))
    fireEvent.change(screen.getByPlaceholderText(/trip to mexico/i), {
      target: { value: 'trip to mexico city' },
    })
    fireEvent.change(screen.getByPlaceholderText(/cooking/i), {
      target: { value: 'cooking, football' },
    })
    completeSetup()

    await screen.findByText(/you're all set!/i)

    // profiles: an update (the row exists already), stamped + confirmed via
    // .select('id') — the same verification shape as the library delete.
    const profileWrites = supabaseMock.writes.filter((write) => write.table === 'profiles')
    expect(profileWrites).toHaveLength(1)
    expect(profileWrites[0].op).toBe('update')
    expect(profileWrites[0].row).toMatchObject({
      target_language: 'es',
      onboarded_at: expect.any(String),
    })
    expect(profileWrites[0].row).not.toHaveProperty('level')
    expect(profileWrites[0].row).not.toHaveProperty('goals')
    expect(profileWrites[0].row).not.toHaveProperty('interests')
    const profileChain = supabaseMock.chains.filter((chain) => chain.table === 'profiles')[0]
    expect(profileChain.writeSelected).toBe(true)
    expect(profileChain.filters).toEqual([['id', 'test-user']])

    // user_languages: the single write of the learner context.
    const languageWrites = supabaseMock.writes.filter((write) => write.table === 'user_languages')
    expect(languageWrites).toHaveLength(1)
    expect(languageWrites[0].op).toBe('upsert')
    expect(languageWrites[0].row).toEqual({
      user_id: 'test-user',
      language: 'es',
      level: 'B1',
      goals: 'trip to mexico city',
      interests: 'cooking, football',
    })
  })

  it('never reaches the complete step when the profiles update reports an error', async () => {
    seed.profilesWriteError = { message: 'row missing' }
    render(<OnboardingPage />)
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))
    completeSetup()

    await waitFor(() => {
      // The failed write is not followed by the user_languages write.
      const writes = supabaseMock.writes
      expect(writes.length).toBeGreaterThan(0)
      expect(writes.every((write) => write.table === 'profiles')).toBe(true)
    })
    expect(screen.queryByText(/you're all set!/i)).not.toBeInTheDocument()
    // Still on the goals step: the Setup Error toast fired over it.
    expect(screen.getByRole('button', { name: /complete setup/i })).toBeVisible()
  })
})
