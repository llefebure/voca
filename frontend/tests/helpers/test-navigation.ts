import { vi } from 'vitest'

/**
 * Mock of `next/navigation` for jsdom tests. `usePathname` returns the current
 * module's pathname placeholder; `useRouter().push` is recorded so tests can
 * assert redirects (auth gates, onboarding).
 */

export const navigationState = { pushes: [] as string[] }

export function createNavigationMock(pathname = '/test') {
  return {
    useRouter: () => ({
      push: vi.fn((href: string) => {
        navigationState.pushes.push(href)
      }),
      replace: vi.fn(),
      back: vi.fn(),
      forward: vi.fn(),
      refresh: vi.fn(),
      prefetch: vi.fn(),
    }),
    usePathname: () => pathname,
    useSearchParams: () => new URLSearchParams(),
    useParams: () => ({}),
    notFound: () => {
      throw new Error('next/navigation notFound() called (mock)')
    },
    redirect: () => {
      throw new Error('next/navigation redirect() called (mock)')
    },
  }
}
