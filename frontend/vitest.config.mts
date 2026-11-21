import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tsconfigPaths from 'vite-tsconfig-paths'

// Unit/component tests (offline, deterministic — supabase is mocked, see
// tests/helpers/supabase-mock.ts). Mirrors the backend's offline pytest suite.
// Per docs: node_modules/next/dist/docs/01-app/02-guides/testing/vitest.md
export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['vitest.setup.mts'],
    include: ['tests/**/*.{test,spec}.{ts,tsx}'],
  },
})
