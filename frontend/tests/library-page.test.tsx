import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SupabaseMockOptions } from './helpers/supabase-mock'

// Per-test state read lazily by the supabase mock (functions in TableConfig are
// resolved at query time) — same hoisted-ref pattern as language-context.test.
const seed = vi.hoisted(() => {
  const seedRef = {
    cards: [] as Array<Record<string, unknown>>,
    tables: undefined as unknown as SupabaseMockOptions['tables'],
  }
  seedRef.tables = {
    profiles: { maybeSingle: { id: 'test-user', target_language: 'es', onboarded_at: '2026-03-01T10:00:00Z' } },
    user_languages: { select: [{ language: 'es', last_practiced_at: '2026-03-01T10:00:00Z' }] },
    cards: {
      select: () => seedRef.cards,
      // Deletes keep the canned rows in sync so the refetched page reflects them.
      onDelete: (id: unknown) => {
        seedRef.cards = seedRef.cards.filter((card) => card.id !== id)
      },
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
  return createNavigationMock('/library')
})

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-mock="recharts-responsive">{children}</div>
  ),
}))

function makeCards(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `card-${i + 1}`,
    type: 'phrase',
    front: `card front ${i + 1}`,
    back: `card back ${i + 1}`,
    fsrs_data: '{"state":1,"step":0,"stability":null,"difficulty":null,"due":"2026-03-15T09:00:00Z","last_review":null}',
    next_review: null,
    created_at: '2026-03-01T10:00:00Z',
  }))
}

import LibraryPage from '@/app/library/page'
import { LanguageProvider } from '@/components/language-context'
import { supabase } from '@/lib/supabase'
import type { SupabaseMock } from './helpers/supabase-mock'

const supabaseMock = supabase as unknown as SupabaseMock

/** Paged cards chains, oldest built → newest; last one is the live query. */
function lastCardsChain() {
  const cardChains = supabaseMock.chains.filter((chain) => chain.table === 'cards')
  expect(cardChains.length).toBeGreaterThan(0)
  return cardChains[cardChains.length - 1]
}

function pagedCardsChains() {
  return supabaseMock.chains.filter((chain) => chain.table === 'cards' && chain.range)
}

async function renderLibrary() {
  const view = render(
    <LanguageProvider>
      <LibraryPage />
    </LanguageProvider>,
  )
  await new Promise((resolve) => setTimeout(resolve, 350)) // settle + search debounce
  return view
}

beforeEach(() => {
  cleanup()
  seed.cards = makeCards(30)
  supabaseMock.chains.length = 0
  supabaseMock.setUser({ id: 'test-user' })
})

afterEach(() => {
  cleanup()
})

describe('Library pagination', () => {
  it('shows the first page and the X–Y of N footer', async () => {
    await renderLibrary()
    expect(await screen.findByText('card front 1')).toBeVisible()
    expect(screen.getByText('card front 24')).toBeVisible()
    expect(screen.queryByText('card front 25')).not.toBeInTheDocument()
    expect(screen.getByText('Showing 1–24 of 30')).toBeVisible()
    // Paged query shape: range terminator over 24 rows from the start.
    const chained = pagedCardsChains()
    expect(chained[chained.length - 1].range).toEqual([0, 23])
  })

  it('next/prev reloads the adjacent page', async () => {
    await renderLibrary()
    fireEvent.click(screen.getByRole('button', { name: 'Go to next page' }))
    expect(await screen.findByText('card front 25')).toBeVisible()
    expect(screen.getByText('card front 30')).toBeVisible()
    expect(screen.queryByText('card front 24')).not.toBeInTheDocument()
    expect(screen.getByText('Showing 25–30 of 30')).toBeVisible()
    expect(lastCardsChain().range).toEqual([24, 47])

    fireEvent.click(screen.getByRole('button', { name: 'Go to previous page' }))
    expect(await screen.findByText('card front 1')).toBeVisible()
    expect(screen.getByText('Showing 1–24 of 30')).toBeVisible()
    expect(lastCardsChain().range).toEqual([0, 23])
  })

  it('search calls the server with the sanitized ilike or-filter and resets to page 1', async () => {
    await renderLibrary()
    expect(screen.getByText('card front 1')).toBeVisible()

    // `,()*` are special in the or-filter syntax — the term must arrive clean.
    fireEvent.change(screen.getByPlaceholderText('Search your vocabulary...'), {
      target: { value: 'hola, mundo*(' },
    })
    // The server answers the filtered page; pretend only one card matches.
    seed.cards = [
      {
        id: 'card-search',
        type: 'phrase',
        front: 'hola mundo card',
        back: 'hello world card',
        fsrs_data: '{"state":1}',
        next_review: null,
        created_at: '2026-03-01T10:00:00Z',
      },
    ]

    // The debounced server query must carry the sanitized ilike or-filter and
    // the reset-to-page-1 range.
    await waitFor(() => {
      const filtered = pagedCardsChains().filter((chain) => chain.orFilters.length > 0)
      expect(filtered.length).toBeGreaterThan(0)
      const search = filtered[filtered.length - 1]
      expect(search.orFilters).toEqual(['front.ilike.%hola mundo%,back.ilike.%hola mundo%'])
      expect(search.range).toEqual([0, 23])
    })
    expect(await screen.findByText('hola mundo card')).toBeVisible()
    expect(screen.getByText('Showing 1–1 of 1')).toBeVisible()
  })
})

describe('Library delete + pagination clamp', () => {
  it('refetches the current page after delete and steps back from an emptied last page', async () => {
    seed.cards = makeCards(25)
    await renderLibrary()
    fireEvent.click(screen.getByRole('button', { name: 'Go to next page' }))
    expect(await screen.findByText('card front 25')).toBeVisible()

    window.confirm = vi.fn(() => true)
    const cardElement = screen.getByText('card front 25').closest('.group')
    expect(cardElement).not.toBeNull()
    fireEvent.click(within(cardElement as HTMLElement).getByRole('button'))

    // The refetched last page is empty (offset 24 > 0) → step back to page 1.
    expect(await screen.findByText('card front 24')).toBeVisible()
    expect(screen.queryByText('card front 25')).not.toBeInTheDocument()
    expect(screen.getByText('Showing 1–24 of 24')).toBeVisible()
    // Delete refetch kept the old offsets once, then the clamped first page.
    expect(pagedCardsChains().map((chain) => chain.range)).toEqual([
      [0, 23],
      [24, 47],
      [24, 47],
      [0, 23],
    ])
  })
})
