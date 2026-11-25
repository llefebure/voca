import * as React from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LanguageProvider } from '@/components/language-context'

const seed = vi.hoisted(() => ({
  rows: [
    { speaker: 'user', text: 'Enséñame el menú, por favor.', created_at: '2026-03-01T10:00:00Z' },
    {
      speaker: 'system',
      text: '',
      created_at: '2026-03-01T10:00:05Z',
      payload: {
        kind: 'panel_shown',
        data: { panel: { id: 'panel-1', title: 'Carta del día', markdown: '**Menú**' } },
      },
    },
    { speaker: 'tutor', text: 'Aquí tienes la carta.', created_at: '2026-03-01T10:00:10Z' },
    {
      speaker: 'system',
      text: '',
      created_at: '2026-03-01T10:01:00Z',
      payload: {
        kind: 'panel_shown',
        data: {
          panel: {
            id: 'panel-2',
            title: 'Diálogo',
            markdown: '1. ¿Qué pides?',
          },
        },
      },
    },
  ],
}))

vi.mock('@/lib/supabase', async () => {
  const { createSupabaseMock } = await import('./helpers/supabase-mock')
  return {
    supabase: createSupabaseMock({
      tables: {
        sessions: {
          maybeSingle: { status: 'completed', created_at: '2026-03-01T09:59:00Z', end_time: '2026-03-01T10:30:00Z' },
        },
        transcripts: { select: seed.rows },
      },
    }),
  }
})

vi.mock('next/navigation', async () => {
  const { createNavigationMock } = await import('./helpers/test-navigation')
  return createNavigationMock('/')
})

import TranscriptPage from '@/app/history/[sessionId]/page'

// React's use(): pre-tag the resolved params promise (what Next prerendered
// params carry) so the page unwraps synchronously instead of suspending.
function transcriptParams(sessionId: string) {
  const value = { sessionId }
  const promise = Promise.resolve(value)
  const tagged = promise as Promise<typeof value> & { status?: string; value?: typeof value }
  tagged.status = 'fulfilled'
  tagged.value = value
  return tagged
}

function renderTranscript() {
  return render(
    <LanguageProvider>
      <TranscriptPage params={transcriptParams('sess-1')} />
    </LanguageProvider>,
  )
}

afterEach(cleanup)

describe('Transcript view with canvas artifacts', () => {
  it('splits the view: chat left, artifacts in a tabbed panel right', async () => {
    renderTranscript()
    expect(await screen.findByTestId('transcript-artifacts')).toBeVisible()
    // Chat lines render in the split's left column; system rows are skipped.
    expect(screen.getByText('Enséñame el menú, por favor.')).toBeVisible()
    expect(screen.getByText('Aquí tienes la carta.')).toBeVisible()
    // Two artifacts → tabs; the first artifact is selected by default.
    expect(screen.getByRole('tab', { name: /Carta del día/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: /Diálogo/ })).toBeVisible()
    expect(screen.getByText('Menú')).toBeVisible()
    expect(screen.queryByText('¿Qué pides?')).toBeNull()
    // Switching tabs swaps the artifact content.
    fireEvent.click(screen.getByRole('tab', { name: /Diálogo/ }))
    expect(screen.getByText('¿Qué pides?')).toBeVisible()
  })

  it('shows no artifact panel when the session generated none', async () => {
    // Mutate the captured array in place: the mock binds the reference.
    ;(seed.rows as unknown[]).splice(0, seed.rows.length)
    ;(seed.rows as unknown[]).push(
      { speaker: 'user', text: '¡Hola!', created_at: '2026-03-01T10:00:00Z' },
      { speaker: 'tutor', text: '¡Hola! ¿Qué tal?', created_at: '2026-03-01T10:00:10Z' },
    )
    renderTranscript()
    expect(await screen.findByText('¡Hola!')).toBeVisible()
    expect(screen.queryByTestId('transcript-artifacts')).toBeNull()
  })
})
