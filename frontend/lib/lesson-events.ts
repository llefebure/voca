// Lesson payload types shared by the SSE proxy, the chat page, and the lesson
// components. Mirrors the backend's material primitives / lesson instances
// (services/lesson_material.py, services/lesson_flow.py) — keep in sync.

export type MaterialBlock =
  | { type: 'scenario'; setting: string; learner_role: string; tutor_role: string; goal: string }
  | { type: 'text'; title?: string | null; markdown: string }
  | { type: 'dialogue'; turns: { speaker: 'tutor' | 'learner'; text: string }[] }
  | { type: 'questions'; items: string[] }
  | { type: 'tasks'; items: { task: string; hint?: string | null }[] }
  | { type: 'word_bank'; items: string[] }

export type LessonSpec = {
  template: string
  title: string
  topic?: string | null
  scenario?: string | null
  objectives?: string[]
  minutes?: number | null
}

export type LessonTargetCard = { id: string; front: string; back: string }

export type LessonGrade = {
  card_id: string
  outcome: string
  bonus_use?: boolean
  evidence?: string
}

export type LessonSummary = {
  headline: string
  positives: string[]
  key_phrases: string[]
  bonus_uses?: string[]
}

export type LessonInstance = {
  id: string
  status: 'proposed' | 'active' | 'completed' | 'declined'
  spec: LessonSpec
  material: MaterialBlock[]
  target_cards: LessonTargetCard[]
  reason: string
  intro_line: string
  proposed_at: string
  accepted_at?: string | null
  completed_at?: string | null
  declined_reason?: string | null
  grades?: LessonGrade[]
  summary?: LessonSummary | null
}

/**
 * The typed data parts the chat stream carries (`data-status`, `data-proposal_ready`,
 * …), mirroring the backend's SSE frames. The AI SDK routes these into
 * `message.parts` where `part.type` is `data-${NAME}` and `part.data` is the payload.
 */
export type ChatDataTypes = {
  status: { text: string }
  proposal_ready: { lesson: LessonInstance }
  lesson_started: { lesson: LessonInstance }
  lesson_completed: { lesson: LessonInstance }
  lesson_declined: { lesson_id: string; title?: string | null; reason?: string | null }
}

/**
 * Older stored rows carry gemma's literal \n sequences (the model double-escapes
 * inside tool-arg strings); decode them for display when replaying payloads.
 */
export function cleanEscapedText<T>(value: T): T {
  if (typeof value === 'string') {
    return value
      .replace(/\\r\\n/g, '\n')
      .replace(/\\r/g, '\n')
      .replace(/\\n/g, '\n')
      .replace(/\\t/g, '\t') as T
  }
  if (Array.isArray(value)) return value.map((item) => cleanEscapedText(item)) as T
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value)) out[key] = cleanEscapedText(item)
    return out as T
  }
  return value
}
