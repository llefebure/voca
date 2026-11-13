import { OLLAMA_URL } from '@/lib/api'
import { DEFAULT_LANGUAGE, ttsFor } from '@/lib/languages'

/**
 * Proxies speech synthesis to the local Ollama server so the browser never
 * talks to Ollama directly (avoids CORS and keeps URLs server-side).
 *
 * POST { text, lang? } -> audio/wav (24 kHz PCM; model/voice resolved per
 * target language in lib/languages.ts — currently Spanish only).
 */
export async function POST(request: Request) {
  const { text, lang } = (await request.json()) as { text?: string; lang?: string }

  if (!text || !text.trim()) {
    return Response.json({ error: 'text is required' }, { status: 400 })
  }

  const { model, voice } = ttsFor(lang ?? DEFAULT_LANGUAGE)

  const upstream = await fetch(`${OLLAMA_URL}/v1/audio/speech`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model, voice, input: text }),
  })

  if (!upstream.ok || !upstream.body) {
    const detail = await upstream.text().catch(() => '')
    return Response.json(
      { error: `TTS failed (${upstream.status})`, detail: detail.slice(0, 300) },
      { status: 502 },
    )
  }

  return new Response(upstream.body, {
    headers: {
      'Content-Type': 'audio/wav',
      'Cache-Control': 'no-store',
    },
  })
}
