import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PracticedLanguage } from '@/components/language-context'
import type { SupabaseMockOptions } from './helpers/supabase-mock'

// Per-test state read lazily by the supabase mock (functions in TableConfig are
// resolved at query time). Everything must be defined inside `vi.hoisted`: the
// mock factory runs while the file's imports are evaluated, before the module
// body, so a module-level `seed.tables = {...}` assignment would be too late.
const seed = vi.hoisted(() => {
  const seedRef = {
    userLanguages: [] as Array<Partial<PracticedLanguage> & { language: string }>,
    profileUpdateError: null as { message: string } | null,
    tables: undefined as unknown as SupabaseMockOptions['tables'],
  }
  // Closures must read `seedRef` (the object tests mutate), not local copies.
  seedRef.tables = {
    profiles: {
      maybeSingle: { id: 'test-user', target_language: 'es' },
      writeError: () => seedRef.profileUpdateError,
    },
    user_languages: { select: () => seedRef.userLanguages },
  }
  return seedRef
})

vi.mock('@/lib/supabase', async () => {
  const { createSupabaseMock } = await import('./helpers/supabase-mock')
  return {
    supabase: createSupabaseMock({ tables: seed.tables as never }),
  }
})

import { LanguageProvider, useLanguage } from '@/components/language-context'
import { supabase } from '@/lib/supabase'
import type { SupabaseMock } from './helpers/supabase-mock'

const supabaseMock = supabase as unknown as SupabaseMock

function Probe() {
  const { activeLanguage, loading, practicedLanguages, toggleLanguage } = useLanguage()
  return (
    <div>
      <div data-testid="loading">{String(loading)}</div>
      <div data-testid="active">{activeLanguage ?? 'none'}</div>
      <div data-testid="languages">
        {practicedLanguages.map((l) => `${l.language}@${l.last_practiced_at ?? '-'}`).join(',')}
      </div>
      <button onClick={() => void toggleLanguage('fr')}>toggle-fr</button>
      <button onClick={() => void toggleLanguage('es')}>toggle-es-same</button>
    </div>
  )
}

function renderProbe() {
  return render(
    <LanguageProvider>
      <Probe />
    </LanguageProvider>,
  )
}

beforeEach(() => {
  cleanup()
  seed.profileUpdateError = null
  seed.userLanguages = []
  supabaseMock.writes.length = 0
  supabaseMock.setUser({ id: 'test-user' })
})

describe('LanguageProvider', () => {
  it('exposes the profile target language and sorts rows newest-practiced first', async () => {
    seed.userLanguages = [
      { language: 'es', last_practiced_at: '2026-03-01T10:00:00Z' },
      { language: 'fr', last_practiced_at: '2026-03-05T10:00:00Z' },
      { language: 'ro' }, // never practiced: sinks to the bottom
    ]
    renderProbe()
    expect(await screen.findByTestId('loading')).toHaveTextContent('false')
    expect(screen.getByTestId('active')).toHaveTextContent('es')
    expect(screen.getByTestId('languages')).toHaveTextContent('fr@2026-03-05T10:00:00Z')
    expect(screen.getByTestId('languages')).toHaveTextContent('es@2026-03-01T10:00:00Z')
    expect(screen.getByTestId('languages')).toHaveTextContent('ro@-')
  })

  it('signed out: the context clears instead of rendering a language', async () => {
    renderProbe()
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('es'))

    supabaseMock.setUser(null)
    supabaseMock.emitAuthEvent('SIGNED_OUT')
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('none'))
    expect(screen.getByTestId('languages')).toHaveTextContent('')
  })

  it('toggleLanguage persists the pointer and moves the language to the front', async () => {
    seed.userLanguages = [{ language: 'es', last_practiced_at: '2026-03-01T10:00:00Z' }]
    renderProbe()
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('es'))

    fireEvent.click(screen.getByText('toggle-fr'))
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('fr'))
    expect(supabaseMock.writes).toEqual([
      { table: 'profiles', op: 'update', row: { target_language: 'fr' } },
    ])
    expect(screen.getByTestId('languages')).toHaveTextContent('fr@-')
    expect(screen.getByTestId('languages')).toHaveTextContent('es@2026-03-01T10:00:00Z')
  })

  it('toggleLanguage to the active code only re-renders locally (no write)', async () => {
    renderProbe()
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('es'))
    fireEvent.click(screen.getByText('toggle-es-same'))
    await waitFor(() => expect(supabaseMock.writes).toHaveLength(0))
    expect(screen.getByTestId('active')).toHaveTextContent('es')
  })

  it('toggleLanguage reverts the optimistic switch when the write fails', async () => {
    seed.profileUpdateError = { message: 'RLS denied' }
    seed.userLanguages = [{ language: 'es' }]
    renderProbe()
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('es'))

    fireEvent.click(screen.getByText('toggle-fr'))
    await waitFor(() =>
      expect(supabaseMock.writes).toEqual([
        { table: 'profiles', op: 'update', row: { target_language: 'fr' } },
      ]),
    )
    // The pointer is the source of truth: back to Spanish, fr not added to rows.
    await waitFor(() => expect(screen.getByTestId('active')).toHaveTextContent('es'))
    await waitFor(() => expect(screen.getByTestId('languages')).not.toHaveTextContent('fr'))
  })
})
