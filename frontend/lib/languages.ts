// Target (learning) languages Voca can tutor. The interface stays English;
// this is the single place language names and per-language TTS config live,
// mirroring the backend's `services/languages.py`. Adding a language = adding
// it here (backend + picker) once its models exist.

export type LanguageCode = 'es'

export const SUPPORTED_LANGUAGES: { code: LanguageCode; name: string }[] = [
  { code: 'es', name: 'Spanish' },
]

// Shown disabled in pickers until they are actually supported.
export const UPCOMING_LANGUAGES = ['French', 'German', 'Italian', 'Portuguese']

export const DEFAULT_LANGUAGE: LanguageCode = 'es'

export function languageName(code?: string | null): string {
  return SUPPORTED_LANGUAGES.find((l) => l.code === code)?.name ?? 'Spanish'
}

type TtsConfig = { model: string; voice: string }

const TTS_BY_LANGUAGE: Record<LanguageCode, TtsConfig> = {
  // Speech model + voice served by Ollama (Spanish, PCM WAV via /v1/audio/speech).
  // Env overrides only matter inside the TTS proxy route (server side).
  es: {
    model: process.env.TTS_MODEL ?? 'phonon:40m-es',
    voice: process.env.TTS_VOICE ?? 'Alicia',
  },
}

export function ttsFor(code?: string | null): TtsConfig {
  return (code !== null && TTS_BY_LANGUAGE[code as LanguageCode]) || TTS_BY_LANGUAGE.es
}

/** Lesson template ids from the planner, for display purposes. */
export const LESSON_TEMPLATE_NAMES: Record<string, string> = {
  role_play: 'Role Play',
  reading_comprehension: 'Reading Comprehension',
  free_conversation: 'Free Conversation',
}

export function lessonTemplateName(templateId?: string | null): string {
  return (templateId && LESSON_TEMPLATE_NAMES[templateId]) || 'Conversation practice'
}
