import * as React from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { TooltipProvider } from '@/components/ui/tooltip'
import { LanguageProvider } from '@/components/language-context'

const recap = vi.hoisted(() => ({
  value: {
    positives: ['lo usó bien'],
    key_corrections: [] as string[],
    next_time_preview: 'tomorrow',
    user_word_count: 12,
    new_cards: [{ type: 'phrase', front: 'la cuenta', back: 'the bill' }],
    reviewed_cards: [
      { front: 'quisiera', back: 'I would like', rating: 4 },
      { front: 'la cuenta', back: 'the bill', rating: 1 },
      { front: 'agotado', back: 'exhausted', rating: null },
    ],
  },
}))

vi.mock('@/lib/supabase', async () => {
  const { createSupabaseMock } = await import('./helpers/supabase-mock')
  return {
    supabase: createSupabaseMock({
      tables: {
        sessions: { single: { recap: recap.value, user_id: 'test-user' } },
      },
    }),
  }
})

vi.mock('next/navigation', async () => {
  const { createNavigationMock } = await import('./helpers/test-navigation')
  return createNavigationMock('/')
})

import RecapPage from '@/app/recap/[sessionId]/page'

// React's use(): pre-tag the resolved promise the way Next's prerendered
// params carry it, so the page unwraps synchronously instead of suspending.
function recapPageParams() {
  const value = { sessionId: 'sess-1' }
  const promise = Promise.resolve(value)
  const tagged = promise as Promise<typeof value> & { status?: string; value?: typeof value }
  tagged.status = 'fulfilled'
  tagged.value = value
  return tagged
}

function renderRecap() {
  return render(
    <LanguageProvider>
      <TooltipProvider>
        <RecapPage params={recapPageParams()} />
      </TooltipProvider>
    </LanguageProvider>,
  )
}

afterEach(cleanup)

describe('Recap review scorecard', () => {
  it('renders one icon row per reviewed word, labeled for hover', async () => {
    renderRecap()
    await screen.findByText('Review Outcomes')
    expect(screen.getByText('quisiera')).toBeVisible()
    expect(screen.getByText('I would like')).toBeVisible()
    // "la cuenta" legitimately appears in both the scorecard and the
    // new-cards list (agotado does not).
    expect(screen.getAllByText('la cuenta').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('agotado')).toBeVisible()
    // The scorecard section is distinct from the harvested new-cards list.
    expect(screen.getByText('Review Material')).toBeVisible()
    // Bare icons carry the rating text for hover (aria-labels on the marks).
    expect(screen.getByLabelText('Easy')).toBeVisible()
    expect(screen.getByLabelText('Again')).toBeVisible()
    expect(screen.getByLabelText('Not attempted')).toBeVisible()
  })

  it('shows an empty state when nothing was reviewed', async () => {
    recap.value.reviewed_cards = []
    renderRecap()
    expect(await screen.findByText('No review words came up this session.')).toBeVisible()
    // The harvested new cards are unaffected.
    expect(screen.getByText('la cuenta')).toBeVisible()
  })
})
