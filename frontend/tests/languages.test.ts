import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
  languageName,
  ttsFor,
} from '@/lib/languages'

// The DB's `public.language_code` domain in supabase/migrations/ is the single
// canonical definition of the supported-language codes; this map must mirror
// it (see the comment in lib/languages.ts).
const MIGRATIONS_DIR = path.resolve(__dirname, '../../supabase/migrations')
const DOMAIN_LINE =
  /CREATE\s+DOMAIN\s+public\.language_code\s+AS\s+TEXT\s+CHECK\s*\(\s*VALUE\s+IN\s*\(([^)]*)\)\)/i

describe('languages', () => {
  it('exposes Spanish as the only supported language today', () => {
    expect(SUPPORTED_LANGUAGES).toEqual([{ code: 'es', name: 'Spanish' }])
    expect(DEFAULT_LANGUAGE).toBe('es')
  })

  it('languageName falls back to Spanish for unknown/missing codes', () => {
    expect(languageName('es')).toBe('Spanish')
    expect(languageName('fr')).toBe('Spanish')
    expect(languageName(null)).toBe('Spanish')
    expect(languageName(undefined)).toBe('Spanish')
  })

  it('ttsFor returns the Spanish speech model/voice for any code', () => {
    expect(ttsFor('es')).toEqual({ model: 'phonon:40m-es', voice: 'Alicia' })
    // Unknown languages still resolve to a (sensible default) config.
    expect(ttsFor('fr').model).toBe('phonon:40m-es')
  })

  it('mirrors the language_code domain defined in the migrations', () => {
    const lines: string[] = []
    for (const file of readdirSync(MIGRATIONS_DIR).sort()) {
      lines.push(...readFileSync(path.join(MIGRATIONS_DIR, file), 'utf8').split('\n'))
    }
    const domainLines = lines
      .map((line) => DOMAIN_LINE.exec(line))
      .filter((m): m is RegExpExecArray => m !== null)
    expect(domainLines, 'domain line missing from the migrations').toHaveLength(1)
    const domainCodes = domainLines[0][1]
      .split(',')
      .map((code) => code.trim().replace(/^['"]|['"]$/g, ''))
    expect(SUPPORTED_LANGUAGES.map((lang) => lang.code)).toEqual([...domainCodes].sort())
  })
})
