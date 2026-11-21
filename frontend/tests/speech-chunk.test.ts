import { describe, expect, it } from 'vitest'
import { splitSpeechChunk, stripForSpeech } from '@/lib/speech-chunk'

/**
 * Dense behavior tables for the streaming-TTS text piece (see
 * plans/streaming-tts.md): boundaries only at whitespace-following sentence
 * punctuation/newlines (decimals like "1.5" and trailing abbreviations like
 * "Sr." stay whole), a ~220-char hard cap, and Markdown stripping that keeps
 * spoken content.
 */
describe('splitSpeechChunk', () => {
  it.each([
    // [input, expected-leading-completed-text]
    ['', ''],
    ['Hola', ''],
    ['Hola.', ''],
    ['Hola, ¿cómo estás', ''],
    // One sentence completes only when whitespace follows the punctuation.
    ['Hola. ', 'Hola. '],
    ['Hola. ¿Qué tal?', 'Hola. '],
    ['Uno. Dos. Tres', 'Uno. '],
    ['¡Hola!', ''],
    ['¡Hola! Encantado.', '¡Hola! '],
    // Spanish inverted marks need nothing special: split on the closing mark.
    ['¿Cómo se dice? No sé.', '¿Cómo se dice? '],
    ['¡Sorpresa! ¿Viste eso? Bien.', '¡Sorpresa! '],
    // Decimals don't split: no whitespace after the dot.
    ['Tengo 1.5 litros.', ''],
    ['Compré 1.5 kilos. Hola', 'Compré 1.5 kilos. '],
    // A trailing "Sr." (end of buffer) is not a boundary.
    ['Me llamo Sr.', ''],
    ['Soy el Sr. Ruiz', 'Soy el Sr. '],
    // Ellipses (single glyph and three dots).
    ['Espera… aún no', 'Espera… '],
    ['Espera… ¿sí?', 'Espera… '],
    ['Y luego… nada', 'Y luego… '],
    ['Y luego... nada', 'Y luego... '],
    // Newlines are boundaries even without punctuation.
    ['Primera línea\nSegunda', 'Primera línea\n'],
    ['Salta el mensaje\n\nY sigue', 'Salta el mensaje\n'],
    // Mixed: markdown-ish prefixes don't block sentence detection.
    ['**Hola.** Bien. Gracias', '**Hola.** Bien. '],
    // Formatting directly after the punctuation blocks the whitespace...
    ['**Hola.** Bien.', ''],
    ['- Uno - Dos', ''],
  ])('%s → %s', (input, expected) => {
    expect(splitSpeechChunk(input)).toBe(expected)
  })

  it('splits repeatedly, one leading chunk per call', () => {
    const text = 'Uno. Dos. Tres.'
    const first = splitSpeechChunk(text)
    expect(first).toBe('Uno. ')
    const second = splitSpeechChunk(text.slice(first.length))
    expect(second).toBe('Dos. ')
  })

  it('cut at the hard cap lands on the last space within it', () => {
    const text = 'palabra '.repeat(40) // 320 chars, no sentence punctuation
    const chunk = splitSpeechChunk(text)
    expect(chunk.length).toBeLessThanOrEqual(220)
    expect(chunk.length).toBeGreaterThan(200)
    expect(chunk.endsWith('palabra')).toBe(true)
    // The rest of the sentence continues once the stream grows further.
    expect(splitSpeechChunk(`${text.slice(chunk.length)} y fin. Chau`)).not.toBe('')
  })

  it('hard-cuts at the cap when there is no space at all', () => {
    const chunk = splitSpeechChunk('x'.repeat(300))
    expect(chunk).toBe('x'.repeat(220))
  })
})

describe('stripForSpeech', () => {
  it.each([
    // [input, spoken text]
    ['', ''],
    ['Texto plano.', 'Texto plano.'],
    // Fenced code blocks disappear whole, dangling markers included.
    ['Mira:\n```py\nprint("hola")\n```\nAdiós.', 'Mira:\n \nAdiós.'],
    ['empezó el bloque ``` y nunca cerró', 'empezó el bloque  y nunca cerró'],
    // Inline code keeps its content.
    ['Di `hola` fuerte', 'Di hola fuerte'],
    // Images keep alt text, links keep their text.
    ['Mira ![un gato](https://x/g.png)', 'Mira un gato'],
    ['Mira ![un gato](https://x/g.png) y [la RAE](https://rae.es).', 'Mira un gato y la RAE.'],
    // Heading markers are dropped, heading text stays.
    ['## Saludos\n¡Hola!', 'Saludos\n¡Hola!'],
    // List bullets (unordered and ordered) are dropped, items stay.
    ['- pan\n- leche', 'pan\nleche'],
    ['1. uno\n2. dos', 'uno\ndos'],
    // Emphasis markers are dropped, the words stay.
    ['**Hola** *mundo* ~~adiós~~', 'Hola mundo adiós'],
    ['***Fuerte y lento***', 'Fuerte y lento'],
    ['Enfasis con _guiones bajos_ y __más__', 'Enfasis con guiones bajos y más'],
  ])('%s → %s', (input, expected) => {
    expect(stripForSpeech(input)).toBe(expected)
  })
})
