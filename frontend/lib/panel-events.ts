// Panel payload types shared by the SSE proxy, the chat page, and the panel
// components. Mirrors the backend's panel content primitives
// (services/panel_content.py) — keep in sync.

export type PanelInstance = {
  id: string
  title: string
  /** The panel's content, composed by the tutor directly in markdown. */
  markdown: string
}

/**
 * The typed data parts the chat stream carries (`data-status`, `data-panel_shown`,
 * …), mirroring the backend's SSE frames. The AI SDK routes these into
 * `message.parts` where `part.type` is `data-${NAME}` and `part.data` is the payload.
 */
export type ChatDataTypes = {
  status: { text: string }
  panel_shown: { panel: PanelInstance }
  panel_hidden: { panel_id: string }
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
