'use client'

import * as React from 'react'

import { splitSpeechChunk, stripForSpeech } from '@/lib/speech-chunk'

const MUTED_STORAGE_KEY = 'voca-tts-muted'

/** One TTS chunk waiting in the FIFO queue. */
type SpeechChunk = {
  id: string
  text: string
  lang: string | undefined
  attempts: number
}

/** Per-message streaming state: which part of the grown text is already queued. */
type StreamState = {
  consumed: number
  lastText: string
  /** A too-short sentence held back to merge into the next chunk. */
  carry: string
  lang: string | undefined
}

/** In-flight TTS fetch: at most one at a time; the rest is prefetched playback. */
type PendingFetch = { chunk: SpeechChunk; promise: Promise<Blob> }

/** A fetch failing once is retried once, then the chunk is skipped silently. */
const MAX_FETCH_ATTEMPTS = 2

// The muted preference lives in localStorage, an external store. Toggling in
// this tab notifies local listeners (no `storage` event fires in the writing
// document); cross-tab changes come through the `storage` event.
const mutedListeners = new Set<() => void>()

function subscribeMuted(callback: () => void) {
  mutedListeners.add(callback)
  window.addEventListener('storage', callback)
  return () => {
    mutedListeners.delete(callback)
    window.removeEventListener('storage', callback)
  }
}

function readMutedSnapshot(): boolean {
  return window.localStorage.getItem(MUTED_STORAGE_KEY) === '1'
}

/**
 * Speech playback for tutor messages. Auto-speaks the tutor's reply while it
 * streams: the grown text is cut into sentences (lib/speech-chunk), each one
 * queued FIFO with at most one TTS fetch in flight (the next is prefetched
 * while the current chunk plays). `speak(id, …)` replays a full message over
 * the same queue; `speakStream`/`finishStream` drive the streaming path. The
 * target language selects the model/voice (see lib/languages.ts).
 */
export function useSpeech() {
  // Read localStorage through useSyncExternalStore so no server/client branch
  // taints the hydrated HTML: React hydrates with the server snapshot
  // (unmuted) and re-renders with the persisted value afterwards — a localStorage
  // read in a state initializer would instead render a different icon client-
  // side on the first pass (hydration mismatch on the mute button).
  const muted = React.useSyncExternalStore(subscribeMuted, readMutedSnapshot, () => false)
  const [speakingId, setSpeakingId] = React.useState<string | null>(null)

  const mutedRef = React.useRef(false)
  mutedRef.current = muted
  // Generation token: bumped on every stop so in-flight fetches and queued
  // chunks are invalidated atomically.
  const genRef = React.useRef(0)
  const queueRef = React.useRef<SpeechChunk[]>([])
  const prefetchRef = React.useRef<PendingFetch | null>(null)
  const audioRef = React.useRef<HTMLAudioElement | null>(null)
  const urlRef = React.useRef<string | null>(null)
  const drivingRef = React.useRef(false)
  const streamsRef = React.useRef(new Map<string, StreamState>())
  // Message ids whose stream was discarded (stopped or muted mid-stream):
  // speakStream/finishStream ignore them until an explicit speak() revives the id.
  const stoppedRef = React.useRef(new Set<string>())

  const stop = React.useCallback(() => {
    genRef.current += 1
    queueRef.current = []
    prefetchRef.current = null
    for (const id of streamsRef.current.keys()) stoppedRef.current.add(id)
    streamsRef.current.clear()
    audioRef.current?.pause()
    audioRef.current = null
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current)
      urlRef.current = null
    }
    setSpeakingId(null)
  }, [])

  /** Start the next TTS fetch if none is in flight (one at a time, no bursts). */
  const ensurePrefetch = React.useCallback(() => {
    if (prefetchRef.current || queueRef.current.length === 0) return
    const chunk = queueRef.current.shift()!
    prefetchRef.current = { chunk, promise: fetchChunk(chunk) }
  }, [])

  /** Play one blob URL and resolve when it ends, errors, or is paused. */
  const playChunk = React.useCallback((url: string) => {
    return new Promise<void>((resolve) => {
      const audio = new Audio(url)
      audioRef.current = audio
      urlRef.current = url
      const done = () => {
        if (audioRef.current === audio) audioRef.current = null
        resolve()
      }
      audio.onended = done
      audio.onerror = done
      audio.onpause = done
      void audio.play().catch(done)
    })
  }, [])

  /** Single playback driver: serialized fetch + chained Audio via the loop. */
  const drive = React.useCallback(async () => {
    if (drivingRef.current) return
    drivingRef.current = true
    try {
      for (;;) {
        const gen = genRef.current
        if (mutedRef.current) break
        // Acquire the next chunk: the prefetched fetch first, else the FIFO head.
        let pending = prefetchRef.current
        if (pending) prefetchRef.current = null
        else if (queueRef.current.length > 0) {
          const chunk = queueRef.current.shift()!
          pending = { chunk, promise: fetchChunk(chunk) }
        }
        if (!pending) break
        let blob: Blob
        try {
          blob = await pending.promise
        } catch {
          if (gen !== genRef.current) break
          const { chunk } = pending
          if (chunk.attempts + 1 < MAX_FETCH_ATTEMPTS) {
            queueRef.current.unshift({ ...chunk, attempts: chunk.attempts + 1 })
          }
          continue
        }
        if (gen !== genRef.current || mutedRef.current) break
        if (blob.size === 0) continue
        // While this chunk plays, the next fetch is already in flight.
        ensurePrefetch()
        const url = URL.createObjectURL(blob)
        try {
          setSpeakingId(pending.chunk.id)
          await playChunk(url)
        } finally {
          if (urlRef.current === url) urlRef.current = null
          URL.revokeObjectURL(url)
        }
      }
    } finally {
      drivingRef.current = false
      if (queueRef.current.length > 0 || prefetchRef.current) {
        void drive()
      } else if (!audioRef.current) {
        // Nothing is playing or queued (and nothing was started meanwhile).
        setSpeakingId(null)
      }
    }
  }, [ensurePrefetch, playChunk])

  /** Cut a stream's unconsumed text into queued chunks (see speech-chunk.ts). */
  const drainStream = React.useCallback(
    (id: string, stream: StreamState) => {
      let raw = stream.lastText.slice(stream.consumed)
      for (;;) {
        const chunk = splitSpeechChunk(raw)
        if (!chunk) break
        stream.consumed += chunk.length
        raw = raw.slice(chunk.length)
        const spoken = (stream.carry + stripForSpeech(chunk)).trim()
        stream.carry = ''
        if (!spoken) continue
        // Empty/one-glyph sentences are not worth a TTS call: merge into next.
        if (spoken.length < 2) {
          stream.carry = `${spoken} `
          continue
        }
        queueRef.current.push({ id, text: spoken, lang: stream.lang, attempts: 0 })
      }
    },
    [],
  )

  /** Queue whatever is left unconsumed in a stream as its final chunk. */
  const flushStream = React.useCallback((id: string, stream: StreamState) => {
    const remaining = stream.lastText.slice(stream.consumed)
    const spoken = (stream.carry + stripForSpeech(remaining)).trim()
    stream.carry = ''
    stream.consumed = stream.lastText.length
    if (spoken) {
      queueRef.current.push({ id, text: spoken, lang: stream.lang, attempts: 0 })
    }
  }, [])

  /**
   * Streaming entry point, idempotent per (id, grown text): feed the
   * accumulated assistant reply so far; newly-completed sentences join the
   * FIFO. A muted or stopped stream is dead for this message — unmuting takes
   * effect on the next message, never retroactively.
   */
  const speakStream = React.useCallback(
    (id: string, fullText: string, lang?: string) => {
      if (!fullText.trim() || stoppedRef.current.has(id)) return
      if (mutedRef.current) {
        stoppedRef.current.add(id)
        streamsRef.current.delete(id)
        return
      }
      let stream = streamsRef.current.get(id)
      if (!stream) {
        stream = { consumed: 0, lastText: '', carry: '', lang }
        streamsRef.current.set(id, stream)
      }
      if (fullText === stream.lastText) return
      stream.lastText = fullText
      drainStream(id, stream)
      ensurePrefetch()
      void drive()
    },
    [drainStream, ensurePrefetch, drive],
  )

  /** Flush the trailing fragment of a streaming turn as its final chunk. */
  const finishStream = React.useCallback(
    (id: string) => {
      const stream = streamsRef.current.get(id)
      if (!stream) return // never spoken (e.g. restored history): no-op
      streamsRef.current.delete(id)
      if (mutedRef.current) {
        stoppedRef.current.add(id)
        return
      }
      flushStream(id, stream)
      if (queueRef.current.length > 0) {
        ensurePrefetch()
        void drive()
      } else if (!drivingRef.current) {
        setSpeakingId(null)
      }
    },
    [drive, ensurePrefetch, flushStream],
  )

  /** Replay a full message through the same queue (chunked, not one blob). */
  const speak = React.useCallback(
    (id: string, text: string, lang?: string) => {
      if (mutedRef.current || !text.trim()) return
      stop()
      // Explicit replay revives the id even if its stream was stopped before.
      stoppedRef.current.delete(id)
      const stream: StreamState = { consumed: 0, lastText: text, carry: '', lang }
      streamsRef.current.set(id, stream)
      drainStream(id, stream)
      flushStream(id, stream)
      ensurePrefetch()
      void drive()
    },
    [drainStream, flushStream, ensurePrefetch, drive, stop],
  )

  const toggleMuted = React.useCallback(() => {
    const next = !readMutedSnapshot()
    window.localStorage.setItem(MUTED_STORAGE_KEY, next ? '1' : '0')
    mutedRef.current = next
    if (next) stop()
    for (const listener of mutedListeners) listener()
  }, [stop])

  React.useEffect(() => stop, [stop])

  return { muted, toggleMuted, speakingId, speak, stop, speakStream, finishStream }
}

/** Fetch one chunk's WAV through the /api/tts proxy. */
async function fetchChunk(chunk: SpeechChunk): Promise<Blob> {
  const response = await fetch('/api/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: chunk.text, lang: chunk.lang }),
  })
  if (!response.ok) throw new Error(`TTS request failed: ${response.status}`)
  return await response.blob()
}
