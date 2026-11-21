import { describe, expect, it } from 'vitest'
import {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
  languageName,
  lessonTemplateName,
  ttsFor,
} from '@/lib/languages'

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

  it('lessonTemplateName maps known templates, falls back to "Conversation practice"', () => {
    expect(lessonTemplateName('role_play')).toBe('Role Play')
    expect(lessonTemplateName('reading_comprehension')).toBe('Reading Comprehension')
    expect(lessonTemplateName('free_conversation')).toBe('Free Conversation')
    expect(lessonTemplateName('mystery_template')).toBe('Conversation practice')
    expect(lessonTemplateName(null)).toBe('Conversation practice')
    expect(lessonTemplateName('')).toBe('Conversation practice')
  })
})
