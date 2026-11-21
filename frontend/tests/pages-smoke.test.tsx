import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import { LanguageProvider } from '@/components/language-context'

/**
 * Smoke-renders every page route in jsdom with Supabase mocked (canned rows
 * below, defined in vi.hoisted because the mock factory runs while imports are
 * evaluated, before the module body). The contract under test: each page
 * mounts, loads its data and unmounts without crashing — the failure mode
 * typecheck can't see. Deeper behavior lives in focused test files; the
 * real-browser check is the Playwright smoke spec.
 */
const seed = vi.hoisted(() => ({
  tables: {
    profiles: { maybeSingle: { id: 'test-user', target_language: 'es' } },
    user_languages: { select: [{ language: 'es', last_practiced_at: '2026-03-01T10:00:00Z' }] },
    sessions: {
      select: [
        {
          id: 'test-session',
          session_id: 'test-session',
          status: 'completed',
          language: 'es',
          created_at: '2026-03-01T10:00:00Z',
          start_time: '2026-03-01T10:00:00Z',
          end_time: '2026-03-01T10:30:00Z',
          recap: { user_word_count: 42 },
          plan: null,
          user_id: 'test-user',
        },
        {
          id: 'test-session-2',
          session_id: 'test-session-2',
          status: 'active',
          language: 'es',
          created_at: '2026-03-02T10:00:00Z',
          start_time: '2026-03-02T10:00:00Z',
          end_time: null,
          recap: null,
          plan: null,
          user_id: 'test-user',
        },
      ],
      maybeSingle: {
        id: 'test-session',
        session_id: 'test-session',
        status: 'active',
        language: 'es',
        plan: null,
        recap: null,
        user_id: 'test-user',
        created_at: '2026-03-01T10:00:00Z',
        start_time: null,
        end_time: null,
      },
      single: {
        id: 'test-session',
        session_id: 'test-session',
        status: 'completed',
        language: 'es',
        plan: null,
        recap: null,
        user_id: 'test-user',
      },
    },
    transcripts: {
      select: [
        { session_id: 'test-session', speaker: 'user', text: 'Hola. ¿Cómo se dice "good morning"?', created_at: '2026-03-01T10:00:30Z' },
        { session_id: 'test-session', speaker: 'assistant', text: '¡Hola! Se dice "buenos días".', created_at: '2026-03-01T10:00:45Z' },
      ],
    },
    cards: {
      select: [
        { card_id: 1, user_id: 'test-user', language: 'es', front: 'buenos días', back: 'good morning', fsrs_data: '{"state":1,"step":0,"stability":null,"difficulty":null,"due":"2026-03-15T09:00:00Z","last_review":null}', next_review: '2026-03-15T09:00:00Z', created_at: '2026-03-01T10:00:00Z' },
        { card_id: 2, user_id: 'test-user', language: 'es', front: 'gracias', back: 'thank you', fsrs_data: '{"state":2,"step":null,"stability":3.2,"difficulty":4.5,"due":"2026-03-20T09:00:00Z","last_review":"2026-03-13T09:00:00Z"}', next_review: '2026-03-20T09:00:00Z', created_at: '2026-03-02T10:00:00Z' },
        { card_id: 3, user_id: 'test-user', language: 'es', front: 'hasta luego', back: 'see you later', fsrs_data: '{"state":1,"step":0,"stability":null,"difficulty":null,"due":"2026-03-16T09:00:00Z","last_review":null}', next_review: null, created_at: '2026-03-03T10:00:00Z' },
      ],
    },
    card_reviews: {
      select: [
        { card_id: 1, rating: 3, reviewed_at: '2026-03-05T10:00:00Z', session_id: 'test-session' },
        { card_id: 2, rating: 1, reviewed_at: '2026-03-06T10:00:00Z', session_id: 'test-session' },
      ],
    },
  },
}))

// The pages also call the FastAPI backend over HTTP (e.g. history's session
// list): stub fetch globally with canned responses.
const BACKEND_SESSIONS = [
  {
    session_id: 'test-session',
    status: 'completed',
    language: 'es',
    created_at: '2026-03-01T10:00:00Z',
    start_time: '2026-03-01T10:00:00Z',
    end_time: '2026-03-01T10:30:00Z',
    recap: { user_word_count: 42 },
    plan: null,
  },
  {
    session_id: 'test-session-2',
    status: 'active',
    language: 'es',
    created_at: '2026-03-02T10:00:00Z',
    start_time: '2026-03-02T10:00:00Z',
    end_time: null,
    recap: null,
    plan: null,
  },
]

vi.stubGlobal(
  'fetch',
  vi.fn(async (input: unknown) => {
    const url = typeof input === 'string' ? input : String((input as { url?: string })?.url ?? input)
    const ok = { ok: true, status: 200, headers: new Headers(), json: async () => ({}) }
    if (url.includes('/sessions')) {
      return { ...ok, json: async () => ({ sessions: BACKEND_SESSIONS }) }
    }
    if (url.includes('/api/tts')) {
      return { ...ok, blob: async () => new Blob(['WAV']) }
    }
    return { ok: false, status: 404, json: async () => ({}) }
  }),
)

vi.mock('@/lib/supabase', async () => {
  const { createSupabaseMock } = await import('./helpers/supabase-mock')
  return { supabase: createSupabaseMock({ tables: seed.tables as never }) }
})

// Recharts' ResponsiveContainer drives a requestAnimationFrame/ResizeObserver
// loop that never lets React's act() settle in jsdom. Chart internals are out
// of scope for the offline suite (the Playwright smoke covers real pages).
vi.mock('recharts', () => {
  const passthrough = (tag: string) => {
    const Component = ({ children }: { children?: React.ReactNode }) => (
      <div data-mock={`recharts-${tag}`}>{children}</div>
    )
    Component.displayName = `RechartsMock${tag}`
    return Component
  }
  return {
    Bar: passthrough('bar'),
    BarChart: passthrough('barchart'),
    CartesianGrid: passthrough('grid'),
    Legend: passthrough('legend'),
    ResponsiveContainer: passthrough('responsive'),
    Tooltip: passthrough('tooltip'),
    XAxis: passthrough('xaxis'),
    YAxis: passthrough('yaxis'),
  }
})

vi.mock('next/navigation', async () => {
  const { createNavigationMock } = await import('./helpers/test-navigation')
  return createNavigationMock('/history')
})

vi.mock('@/lib/use-speech', () => ({
  useSpeech: () => ({
    muted: true,
    toggleMuted: vi.fn(),
    speakingId: null,
    speak: vi.fn(async () => {}),
    stop: vi.fn(),
  }),
}))

vi.mock('@ai-sdk/react', () => ({
  useChat: () => ({
    messages: [],
    sendMessage: vi.fn(async () => {}),
    status: 'ready',
    setMessages: vi.fn(),
    stop: vi.fn(),
    error: null,
  }),
}))

import ChatPage from '@/app/page'
import AuthPage from '@/app/auth/page'
import OnboardingPage from '@/app/onboarding/page'
import HistoryPage from '@/app/history/page'
import TranscriptPage from '@/app/history/[sessionId]/page'
import RecapPage from '@/app/recap/[sessionId]/page'
import ProgressPage from '@/app/progress/page'
import LibraryPage from '@/app/library/page'
import ProfilePage from '@/app/profile/page'
import { supabase } from '@/lib/supabase'
import { navigationState } from './helpers/test-navigation'
import type { SupabaseMock } from './helpers/supabase-mock'

const supabaseMock = supabase as unknown as SupabaseMock

/** Render inside the real LanguageProvider; give effects/data loads a beat. */
async function renderPage(ui: ReactElement, { withProvider = true } = {}) {
  const view = render(withProvider ? <LanguageProvider>{ui}</LanguageProvider> : ui)
  // Deliberate settle, not act(): RTL's act() never settles for some pages
  // mounted with Base UI internals in jsdom (pending scheduler work), while
  // rendering completes fine in real time. Assertions use findBy*/waitFor to
  // poll for loaded data.
  await new Promise((resolve) => setTimeout(resolve, 100))
  return view
}

function detailPageParams() {
  // React's use(): pre-tagging the resolved promise (what Next's prerendered
  // params carry) lets it unwrap synchronously in jsdom instead of suspending
  // and never resuming under RTL.
  const value = { sessionId: 'test-session' }
  const promise = Promise.resolve(value)
  ;(promise as Promise<typeof value> & { status?: string; value?: typeof value }).status =
    'fulfilled'
  ;(promise as Promise<typeof value> & { status?: string; value?: typeof value }).value = value
  return { params: promise }
}

beforeEach(() => {
  cleanup()
  navigationState.pushes.length = 0
  supabaseMock.setUser({ id: 'test-user' })
})

afterEach(() => {
  cleanup()
})

describe('page smoke renders (signed in)', () => {
  it('chat page (/)', async () => {
    const view = await renderPage(<ChatPage />)
    expect(screen.getByText('Conversation Tutor')).toBeVisible()
    view.unmount()
  })

  it('auth page (/auth)', async () => {
    const view = await renderPage(<AuthPage />, { withProvider: false })
    expect(screen.getByRole('button', { name: 'Sign In' })).toBeVisible()
    expect(screen.getByLabelText('Email')).toBeVisible()
    view.unmount()
  })

  it('onboarding page (/onboarding)', async () => {
    const view = await renderPage(<OnboardingPage />, { withProvider: false })
    expect(view.container.firstElementChild).not.toBeNull()
    view.unmount()
  })

  it('history list (/history) renders the seeded sessions', async () => {
    const view = await renderPage(<HistoryPage />)
    expect(await screen.findByText('Completed')).toBeVisible()
    expect(screen.getByText('Active')).toBeVisible()
    view.unmount()
  })

  it('transcript detail (/history/[sessionId]) shows the stored lines', async () => {
    const view = await renderPage(<TranscriptPage {...detailPageParams()} />)
    expect(await screen.findByText('Hola. ¿Cómo se dice "good morning"?')).toBeVisible()
    view.unmount()
  })

  it('recap detail (/recap/[sessionId]) tolerates a null recap', async () => {
    const view = await renderPage(<RecapPage {...detailPageParams()} />)
    expect(view.container.firstElementChild).not.toBeNull()
    view.unmount()
  })

  it('progress page (/progress) computes from the seeded rows', async () => {
    const view = await renderPage(<ProgressPage />)
    expect(screen.getByText('Review activity')).toBeVisible()
    // Seeded: 1 of 2 reviews rated >= 3 → 50% recall.
    await screen.findByText('50%')
    view.unmount()
  })

  it('card library (/library) renders the seeded cards', async () => {
    const view = await renderPage(<LibraryPage />)
    expect(screen.getByText('Card Library')).toBeVisible()
    expect(await screen.findByText('buenos días')).toBeVisible()
    expect(screen.getByText('gracias')).toBeVisible()
    view.unmount()
  })

  it('profile page (/profile) renders', async () => {
    const view = await renderPage(<ProfilePage />)
    expect(screen.getByText('My Profile')).toBeVisible()
    view.unmount()
  })
})

describe('auth gates redirect when signed out', () => {
  // Only pages with an unconditional auth check redirect; history/progress/
  // library gate on `activeLanguage` first (null when signed out) and stay
  // inert in this harness — their redirect flow is covered by Playwright.
  it.each(['chat', 'profile'])('%s → /auth', async (page) => {
    supabaseMock.setUser(null)
    const pages: Record<string, ReactElement> = {
      chat: <ChatPage />,
      history: <HistoryPage />,
      progress: <ProgressPage />,
      library: <LibraryPage />,
      profile: <ProfilePage />,
    }
    const view = await renderPage(pages[page])
    await new Promise((resolve) => setTimeout(resolve, 100))
    expect(navigationState.pushes).toContain('/auth')
    view.unmount()
  })
})
