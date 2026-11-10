import { OLLAMA_URL, TTS_MODEL, TTS_VOICE } from '@/lib/api'

/**
 * Proxies speech synthesis to the local Ollama server so the browser never
 * talks to Ollama directly (avoids CORS and keeps URLs server-side).
 *
 * POST { text } -> audio/wav (24 kHz PCM, model phonon:40m-es, voice Alicia).
 */
export async function POST(request: Request) {
  const { text } = (await request.json()) as { text?: string }

  if (!text || !text.trim()) {
    return Response.json({ error: 'text is required' }, { status: 400 })
  }

  const upstream = await fetch(`${OLLAMA_URL}/v1/audio/speech`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: TTS_MODEL, voice: TTS_VOICE, input: text }),
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
