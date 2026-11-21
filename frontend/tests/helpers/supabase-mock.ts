import { vi } from 'vitest'
import type { PracticedLanguage } from '@/components/language-context'

/**
 * Mock of `@/lib/supabase`'s client, covering the query surface Voca's pages
 * use (select/eq/order/single/maybeSingle + upsert/update/insert chains), the
 * way the backend suite mocks its supabase client: canned data, no network.
 *
 * Data is configured per table; every query builder method is a pass-through,
 * so tests pin the *result* for a `(table, terminator)` pair rather than the
 * filter clauses — that's all the UI ever needs to render.
 */

export type FakeUser = { id: string; email?: string }

type TableConfig = {
  /** Result for chains that await without a terminator (list queries). */
  select?: unknown[] | (() => unknown[])
  /** Result for `.maybeSingle()`; default null. */
  maybeSingle?: unknown | (() => unknown | null)
  /** Result for `.single()`; default null. */
  single?: unknown | (() => unknown)
  /** `{ error }` returned by write chains (upsert/update/insert); default null. */
  writeError?: (() => { message: string } | null) | { message: string } | null
}

export type SupabaseMockOptions = {
  /** Signed-in user; null tests the signed-out paths. */
  user?: FakeUser | null
  tables?: Record<string, TableConfig>
}

export type SupabaseMock = {
  emitAuthEvent: (event: string) => void
  from: ReturnType<typeof vi.fn>
  auth: Record<string, ReturnType<typeof vi.fn>>
  /** Switch the signed-in user (also records it for assertions). */
  setUser: (next: FakeUser | null) => void
  /** Every write op performed, in order: upsert/update/insert/delete. */
  writes: Array<{ table: string; op: 'insert' | 'upsert' | 'update' | 'delete'; row: unknown }>
}

export function createSupabaseMock(options: SupabaseMockOptions = {}): SupabaseMock {
  const tables = options.tables ?? {}
  const writes: Array<{ table: string; op: 'insert' | 'upsert' | 'update' | 'delete'; row: unknown }> = []
  let currentUser: FakeUser | null =
    options.user === undefined ? { id: 'test-user' } : options.user

  const authListeners: Array<(event: string) => void> = []

  function value(cfgEntry: unknown): unknown {
    return typeof cfgEntry === 'function' ? cfgEntry() : cfgEntry
  }

  function makeChain(table: string): PromiseLike<unknown> & Record<string, unknown> {
    const cfg: TableConfig = tables[table] ?? {}
    let isWrite = false

    const chain = {
      select: () => chain,
      eq: () => chain,
      neq: () => chain,
      in: () => chain,
      gte: () => chain,
      lte: () => chain,
      gt: () => chain,
      lt: () => chain,
      or: () => chain,
      order: () => chain,
      limit: () => chain,
      range: () => chain,
      insert: (row: unknown) => {
        isWrite = true
        writes.push({ table, op: 'insert', row })
        return chain
      },
      upsert: (row: unknown) => {
        isWrite = true
        writes.push({ table, op: 'upsert', row })
        return chain
      },
      update: (row: unknown) => {
        isWrite = true
        writes.push({ table, op: 'update', row })
        return chain
      },
      delete: () => {
        isWrite = true
        writes.push({ table, op: 'delete', row: undefined })
        return chain
      },
      maybeSingle: () =>
        Promise.resolve({
          data: cfg.maybeSingle !== undefined ? value(cfg.maybeSingle) : null,
          error: null,
        }),
      single: () =>
        Promise.resolve({
          data: cfg.single !== undefined ? value(cfg.single) : null,
          error: null,
        }),
      then: (
        onFulfilled?: (value: { data: unknown; error: unknown }) => unknown,
        onRejected?: (reason: unknown) => unknown,
      ) => {
        // Bare await = a plain list query (`.select(...)....eq(...)` chains).
        // `.maybeSingle()` / `.single()` carry their own table values above.
        const data = isWrite ? null : cfg.select !== undefined ? value(cfg.select) : []
        return Promise.resolve({
          data,
          error: isWrite && cfg.writeError ? value(cfg.writeError) : null,
        }).then(onFulfilled, onRejected)
      },
    }
    return chain as unknown as PromiseLike<unknown> & Record<string, unknown>
  }

  const from = vi.fn((table: string) => makeChain(table))

  // The real client is a plain object here; pages only use `.auth` / `.from`.
  // Closures read `currentUser` so tests can swap the signed-in user at runtime.
  return {
    emitAuthEvent: (event: string) => authListeners.forEach((callback) => callback(event)),
    setUser: (next: FakeUser | null) => {
      currentUser = next
    },
    from,
    writes,
    auth: {
      getUser: vi.fn(async () => ({ data: { user: currentUser }, error: null })),
      getSession: vi.fn(async () => ({ data: { session: currentUser }, error: null })),
      onAuthStateChange: vi.fn((callback: (event: string) => void) => {
        authListeners.push(callback)
        // The real client fires INITIAL_SESSION right after subscribing (async).
        queueMicrotask(() => callback('INITIAL_SESSION'))
        return { data: { subscription: { unsubscribe: () => {} } } }
      }),
      signInWithPassword: vi.fn(async () => ({
        data: { user: currentUser, session: currentUser },
        error: null,
      })),
      signUp: vi.fn(async () => ({
        data: { user: currentUser, session: currentUser },
        error: null,
      })),
      signOut: vi.fn(async () => ({ error: null })),
    },
  }
}

/** Practiced-language rows in the shape user_languages stores. */
export function practicedLanguages(
  rows: Array<Partial<PracticedLanguage> & { language: string }>,
): PracticedLanguage[] {
  return rows.map((row) => ({
    level: null,
    goals: null,
    interests: null,
    last_practiced_at: null,
    ...row,
  }))
}
