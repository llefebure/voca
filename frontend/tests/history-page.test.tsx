import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const seed = vi.hoisted(() => {
  const seedRef = {
    total: 0,
    sessions: [] as Array<Record<string, unknown>>,
    fetchUrls: [] as string[],
  }
  return seedRef
})

vi.stubGlobal(
  'fetch',
  vi.fn(async (input: unknown) => {
    const url = typeof input === 'string' ? input : String((input as { url?: string })?.url ?? input)
    seed.fetchUrls.push(url)
    return {
      ok: true,
      status: 200,
      headers: new Headers(),
      json: async () => ({ sessions: seed.sessions, total: seed.total }),
    }
  }),
)

vi.mock('@/lib/supabase', async () => {
  const { createSupabaseMock } = await import('./helpers/supabase-mock')
  return {
    supabase: createSupabaseMock({
      tables: {
        profiles: { maybeSingle: { id: 'test-user', target_language: 'es', onboarded_at: '2026-03-01T10:00:00Z' } },
        user_languages: { select: [{ language: 'es', last_practiced_at: '2026-03-01T10:00:00Z' }] },
      },
    }),
  }
})

vi.mock('next/navigation', async () => {
  const { createNavigationMock } = await import('./helpers/test-navigation')
  return createNavigationMock('/history')
})

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children?: React.ReactNode }) => (
    <div data-mock="recharts-responsive">{children}</div>
  ),
}))

function makeSessions(count: number, dayOffset: number) {
  return Array.from({ length: count }, (_, i) => ({
    session_id: `sess-${dayOffset + i + 1}`,
    status: i === 0 ? 'completed' : 'active',
    language: 'es',
    created_at: `2026-03-${String((dayOffset + i) % 28 + 1).padStart(2, '0')}T10:00:00Z`,
    start_time: null,
    end_time: '2026-03-01T10:30:00Z',
    recap: null,
    plan: null,
  }))
}

import HistoryPage from '@/app/history/page'
import { LanguageProvider } from '@/components/language-context'

async function renderHistory() {
  const view = render(
    <LanguageProvider>
      <HistoryPage />
    </LanguageProvider>,
  )
  await new Promise((resolve) => setTimeout(resolve, 100))
  return view
}

beforeEach(() => {
  cleanup()
  seed.fetchUrls.length = 0
  seed.total = 120
  seed.sessions = makeSessions(2, 0)
})

afterEach(() => {
  cleanup()
})

describe('History pagination', () => {
  it('fetches the first page with limit/offset and shows the X–Y of N footer', async () => {
    await renderHistory()
    expect(await screen.findByText('Completed')).toBeVisible()
    const lastUrl = seed.fetchUrls[seed.fetchUrls.length - 1]
    expect(lastUrl).toContain('/sessions?')
    expect(lastUrl).toContain('language=es')
    expect(lastUrl).toContain('limit=50')
    expect(lastUrl).toContain('offset=0')
    expect(screen.getByText('Showing 1–2 of 120')).toBeVisible()
    // Total beyond the page → next is offered, prev is not (first page).
    expect(screen.getByRole('button', { name: 'Go to next page' })).toBeVisible()
  })

  it('next/prev refetch with the shifted offset', async () => {
    await renderHistory()
    expect(await screen.findByText('Completed')).toBeVisible()

    fireEvent.click(screen.getByRole('button', { name: 'Go to next page' }))
    expect(await screen.findByText('Showing 51–52 of 120')).toBeVisible()
    const lastUrl = seed.fetchUrls[seed.fetchUrls.length - 1]
    expect(lastUrl).toContain('limit=50')
    expect(lastUrl).toContain('offset=50')

    fireEvent.click(screen.getByRole('button', { name: 'Go to previous page' }))
    expect(await screen.findByText('Showing 1–2 of 120')).toBeVisible()
    expect(seed.fetchUrls[seed.fetchUrls.length - 1]).toContain('offset=0')
  })

  it('single page of results offers no navigation beyond the page', async () => {
    seed.total = 2
    await renderHistory()
    expect(await screen.findByText('Showing 1–2 of 2')).toBeVisible()
    // Total ≤ page size → both controls render inert.
    expect(screen.getByRole('button', { name: 'Go to next page' }).className).toContain(
      'pointer-events-none',
    )
    expect(screen.getByRole('button', { name: 'Go to previous page' }).className).toContain(
      'pointer-events-none',
    )
  })
})
