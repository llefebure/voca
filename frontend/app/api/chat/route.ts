import { createUIMessageStream, createUIMessageStreamResponse, type UIMessage } from 'ai'

import { BACKEND_URL } from '@/lib/api'

/**
 * Proxy between the browser's AI SDK chat and the FastAPI backend.
 *
 * - Forwards the Supabase bearer token from the incoming request.
 * - Maps UIMessages into the `{role, content}` history the backend expects.
 * - Transcodes the backend's JSON SSE frames (`{type: delta|error|done}`) into the
 *   AI SDK UI message stream protocol so `useChat` can consume them.
 */

type VocaUIMessage = UIMessage<Record<string, never>>

const TEXT_PART_ID = 'text'

function textOf(message: UIMessage): string {
  return message.parts
    .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
    .map((part) => part.text)
    .join('')
}

/** Parses the backend's `data: {json}\n\n` SSE frames from a fetch body. */
async function* sseEvents(body: ReadableStream<Uint8Array>) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let boundary = buffer.indexOf('\n\n')
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')

      const line = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!line) continue
      try {
        yield JSON.parse(line.slice('data:'.length))
      } catch {
        // Skip frames that aren't our JSON protocol (e.g. SSE comments).
      }
    }
  }
}

export async function POST(request: Request) {
  const auth = request.headers.get('authorization')
  if (!auth) {
    return Response.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const { messages, sessionId } = (await request.json()) as {
    messages: VocaUIMessage[]
    sessionId?: string
  }

  if (!sessionId) {
    return Response.json({ error: 'No active session' }, { status: 400 })
  }

  const lastUser = [...messages].reverse().find((message) => message.role === 'user')
  if (!lastUser) {
    return Response.json({ error: 'No user message' }, { status: 400 })
  }

  const messageId = crypto.randomUUID()
  let openedText = false

  const stream = createUIMessageStream({
    // Providing the incoming messages puts the stream into persistence mode and
    // supplies a message id for the response; `start` reuses it explicitly.
    originalMessages: messages,
    execute: async ({ writer }) => {
      writer.write({ type: 'start', messageId })
      writer.write({ type: 'start-step' })
      writer.write({ type: 'text-start', id: TEXT_PART_ID })
      openedText = true

      let upstream: Response
      try {
        upstream = await fetch(`${BACKEND_URL}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: auth },
          body: JSON.stringify({
            message: textOf(lastUser),
            session_id: sessionId,
            history: messages
              .filter((message) => message.id !== lastUser.id)
              .map((message) => ({ role: message.role, content: textOf(message) })),
          }),
          signal: request.signal,
        })
      } catch {
        writer.write({ type: 'error', errorText: 'Could not reach the tutor backend.' })
        return
      }

      if (!upstream.ok || !upstream.body) {
        const detail = await upstream
          .json()
          .catch(() => ({ detail: 'Tutor backend error' }))
        writer.write({
          type: 'error',
          errorText:
            typeof detail === 'object' && detail && 'detail' in detail
              ? String(detail.detail)
              : 'Tutor backend error',
        })
        return
      }

      try {
        for await (const event of sseEvents(upstream.body)) {
          if (event.type === 'delta' && typeof event.text === 'string') {
            writer.write({ type: 'text-delta', id: TEXT_PART_ID, delta: event.text })
          } else if (event.type === 'error') {
            writer.write({ type: 'error', errorText: String(event.message ?? 'Tutor error') })
          } else if (event.type === 'done') {
            break
          }
        }
      } catch (error) {
        // Client aborted (user pressed stop) or connection dropped mid-stream.
        if (!request.signal.aborted) {
          writer.write({ type: 'error', errorText: String(error) })
        }
      } finally {
        if (openedText) {
          writer.write({ type: 'text-end', id: TEXT_PART_ID })
        }
        writer.write({ type: 'finish-step' })
        writer.write({ type: 'finish' })
      }
    },
    onError: (error) => String(error),
  })

  return createUIMessageStreamResponse({ stream })
}
