/**
 * Pure text helpers for streaming TTS: cut the tutor's growing Markdown reply
 * into sentence-sized pieces for `/api/tts` and strip Markdown syntax that
 * should never be read aloud. See plans/streaming-tts.md.
 */

/**
 * Sentence-ending punctuation that can open a split. The Spanish inverted
 * marks (`¡`, `¿`) need nothing special: the split happens on the closing
 * mark that follows them.
 */
const SENTENCE_PUNCTUATION = '.!?…'

/**
 * Hard cap: a rambling sentence without any boundary is still spoken — cut at
 * the last space once the buffer reaches this many characters.
 */
const HARD_CAP_CHARS = 220

/**
 * Return the completed leading sentences of `text` (possibly a single
 * hard-cap cut); '' when no boundary has been reached yet.
 *
 * A boundary is a sentence punctuation mark (`.` `!` `?` `…`) or a newline,
 * and sentence punctuation splits only when whitespace follows it — decimals
 * like `1.5` and trailing abbreviations like `Sr.` stay inside the buffer.
 * The returned chunk includes the boundary and one whitespace character past
 * it, so remaining text starts mid-sentence.
 */
export function splitSpeechChunk(text: string): string {
  for (let i = 0; i < text.length; i++) {
    const char = text[i]
    if (char === '\n') return text.slice(0, i + 1)
    if (SENTENCE_PUNCTUATION.includes(char)) {
      const next = text[i + 1]
      if (next !== undefined && /\s/.test(next)) {
        return text.slice(0, i + 2)
      }
    }
    if (i + 1 >= HARD_CAP_CHARS) {
      // No boundary within the cap: fall back to the last space so the cut
      // lands between words, or hard-cut at the cap when there is none.
      const lastSpace = text.lastIndexOf(' ', HARD_CAP_CHARS - 1)
      return lastSpace > 0 ? text.slice(0, lastSpace) : text.slice(0, HARD_CAP_CHARS)
    }
  }
  return ''
}

/**
 * Remove Markdown syntax that is noise when spoken; meaningful text survives
 * (link text, image alt text, emphasized words, list items). Fenced code
 * blocks are dropped whole — reading source code aloud is never useful.
 */
export function stripForSpeech(text: string): string {
  let out = text
  // Fenced code blocks (with their content); a fence opened but never closed
  // just loses its marker — the following prose still gets spoken.
  out = out.replace(/```[\s\S]*?```/g, ' ')
  out = out.replace(/```/g, '')
  // Inline code: keep the content (often example vocabulary/phrases).
  out = out.replace(/`([^`]*)`/g, '$1')
  // Images keep their alt text, links keep their link text.
  out = out.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
  out = out.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
  // Heading and list markers.
  out = out.replace(/^#{1,6}\s+/gm, '')
  out = out.replace(/^\s*[-*+]\s+/gm, '')
  out = out.replace(/^\s*\d+[.)]\s+/gm, '')
  // Emphasis (bold, italic, bold-italic, strikethrough).
  out = out.replace(/(\*\*\*|___)(.+?)\1/g, '$2')
  out = out.replace(/(\*\*|__)(.+?)\1/g, '$2')
  out = out.replace(/(\*|_)(.+?)\1/g, '$2')
  out = out.replace(/~~(.+?)~~/g, '$1')
  return out
}
