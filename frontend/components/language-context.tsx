'use client'

import * as React from 'react'
import { supabase } from '@/lib/supabase'
import { DEFAULT_LANGUAGE } from '@/lib/languages'

/**
 * The active learning language and the user's practiced languages, shared by the
 * sidebar toggle and every page (mounted in the root layout).
 *
 * `profiles.target_language` is the *target language pointer*: the language being
 * practiced right now. Per-language learner details (level/goals/interests) live in
 * the `user_languages` table, one row per language the user has onboarded — rows
 * for directly-picked languages are created lazily by Profile edits or the
 * post-session analysis.
 *
 * If no user is signed in, the context stays empty; the pages themselves redirect
 * to /auth as they do today.
 */

export type PracticedLanguage = {
  language: string
  level: string | null
  goals: string | null
  interests: string | null
  last_practiced_at: string | null
}

const LanguageContext = React.createContext<LanguageContextValue | null>(null)

export type LanguageContextValue = {
  /** The language the user is practicing right now (profiles.target_language). */
  activeLanguage: string | null
  /** The user's language rows, most recently practiced first. */
  practicedLanguages: PracticedLanguage[]
  /** True until the profile pointer + language rows have loaded. */
  loading: boolean
  /** Switch the target language; persists to profiles.target_language. */
  toggleLanguage: (code: string) => Promise<void>
  /** Refetch after external changes (e.g. onboarding finished for a new user). */
  refresh: () => Promise<void>
}

function sortByLastPracticed(rows: PracticedLanguage[]): PracticedLanguage[] {
  return [...rows].sort((a, b) => {
    const aAt = a.last_practiced_at ?? ''
    const bAt = b.last_practiced_at ?? ''
    // Rows never practiced sink to the bottom; otherwise newest first.
    if (!aAt && !bAt) return 0
    if (!aAt) return 1
    if (!bAt) return -1
    return bAt.localeCompare(aAt)
  })
}

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  // Mounted in the root layout (app/layout.tsx) so every page can read it.
  const [activeLanguage, setActiveLanguage] = React.useState<string | null>(null)
  const [practicedLanguages, setPracticedLanguages] = React.useState<PracticedLanguage[]>([])
  const [loading, setLoading] = React.useState(true)

  const refresh = React.useCallback(async () => {
    const {
      data: { user },
    } = await supabase.auth.getUser()
    if (!user) {
      setActiveLanguage(null)
      setPracticedLanguages([])
      return
    }
    const [profileRes, languagesRes] = await Promise.all([
      supabase.from('profiles').select('target_language').eq('id', user.id).maybeSingle(),
      supabase.from('user_languages').select('*').eq('user_id', user.id),
    ])
    setActiveLanguage(profileRes.data?.target_language ?? DEFAULT_LANGUAGE)
    setPracticedLanguages(sortByLastPracticed((languagesRes.data as PracticedLanguage[]) ?? []))
  }, [])

  React.useEffect(() => {
    // supabase-js is an external system: refresh in its subscription callback (the
    // rule's blessed pattern), not from the effect body. An INITIAL_SESSION event
    // fires right after subscribing, so the first load is covered without a direct
    // call; SIGNED_IN/SIGNED_OUT keep the context in sync across logins.
    let mounted = true
    const { data } = supabase.auth.onAuthStateChange((event) => {
      if (event !== 'INITIAL_SESSION' && event !== 'SIGNED_IN' && event !== 'SIGNED_OUT') {
        return
      }
      void refresh().finally(() => {
        if (mounted) setLoading(false)
      })
    })
    return () => {
      mounted = false
      data.subscription.unsubscribe()
    }
  }, [refresh])

  const toggleLanguage = React.useCallback(
    async (code: string) => {
      setActiveLanguage(code)
      const {
        data: { user },
      } = await supabase.auth.getUser()
      if (!user || code === activeLanguage) return
      const { error } = await supabase
        .from('profiles')
        .update({ target_language: code })
        .eq('id', user.id)
      if (error) {
        // Revert the optimistic switch; the pointer is the source of truth.
        setActiveLanguage(activeLanguage)
        return
      }
      // The newly active language moves to the front of the practiced list for the
      // dropdown ordering (its last_practiced_at is unchanged until a session starts).
      setPracticedLanguages((rows) =>
        sortByLastPracticed([
          ...rows.filter((row) => row.language !== code),
          { ...(rows.find((row) => row.language === code) ?? {
              language: code,
              level: null,
              goals: null,
              interests: null,
              last_practiced_at: null,
            }) },
        ]),
      )
    },
    [activeLanguage],
  )

  const value = React.useMemo(
    () => ({ activeLanguage, practicedLanguages, loading, toggleLanguage, refresh }),
    [activeLanguage, practicedLanguages, loading, toggleLanguage, refresh],
  )

  return <LanguageContext value={value}>{children}</LanguageContext>
}

export function useLanguage(): LanguageContextValue {
  const context = React.use(LanguageContext)
  if (!context) {
    throw new Error('useLanguage must be used within a LanguageProvider (app/layout.tsx)')
  }
  return context
}
