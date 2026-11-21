import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSpeech } from '@/lib/use-speech'

/**
 * Queue-level behavior of the streaming speech hook (see
 * plans/streaming-tts.md): sentences flow FIFO in order across interleaved
 * deltas, the next TTS fetch is prefetched while the current chunk plays,
 * stop() atomically invalidates in-flight work, and mute mid-stream clears
 * now and applies from the next message. fetch and Audio are replaced so the
 * suite stays offline.
 */

const audioInstances: FakeAudio[] = []

class FakeAudio {
  playing = false
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  onpause: (() => void) | null = null
  constructor(public url: string) {
    audioInstances.push(this)
  }
  play(): Promise<void> {
    this.playing = true
    return Promise.resolve()
  }
  pause(): void {
    this.playing = false
    this.onpause?.()
  }
}

function endPlaying() {
  for (const audio of audioInstances) {
    if (audio.playing) {
      audio.playing = false
      audio.onended?.()
    }
  }
}

/**
 * Fetch captures the requested chunk text in call order; `deferNext` makes a
 * call wait for an explicit release (for the stop-invalidation test).
 */
let ttsBodies: string[] = []
let deferredCalls: ((body: string) => void)[] = []
let deferNext = false

/**
 * This jsdom environment ships no `localStorage`; the mute preference is
 * persisted through it, so substitute an in-memory implementation.
 */
let mutedStorage: Map<string, string>

function fakeTts(_url: unknown, init?: RequestInit): Promise<Response> {
  const body = (JSON.parse(String(init?.body)) ?? {}) as { text: string }
  if (deferNext) {
    deferNext = false
    return new Promise<Response>((resolve) => {
      deferredCalls.push((released) => {
        ttsBodies.push(released)
        resolve({ ok: true, blob: () => Promise.resolve(new Blob([released])) } as Response)
      })
    })
  }
  ttsBodies.push(body.text)
  return Promise.resolve({
    ok: true,
    blob: () => Promise.resolve(new Blob([body.text])),
  } as Response)
}

/** Settle the async driver with a bounded number of microtask drains. */
async function settle(turns = 20) {
  for (let i = 0; i < turns; i++) {
    await act(async () => {
      await Promise.resolve()
    })
  }
}

/** Let the driver run until the fetch mock has been called exactly n times. */
async function untilFetched(n: number) {
  for (let guard = 0; guard < 500 && ttsBodies.length < n; guard++) {
    await settle(1)
  }
  expect(ttsBodies.length).toBe(n)
}

beforeEach(() => {
  audioInstances.length = 0
  ttsBodies = []
  deferredCalls = []
  deferNext = false
  mutedStorage = new Map()
  vi.stubGlobal('Audio', FakeAudio)
  vi.stubGlobal('fetch', vi.fn(fakeTts))
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => mutedStorage.get(key) ?? null,
    setItem: (key: string, value: string) => {
      mutedStorage.set(key, value)
    },
  })
  Object.defineProperty(URL, 'createObjectURL', {
    value: (input: Blob) => `blob:${input.size}`,
    configurable: true,
  })
  Object.defineProperty(URL, 'revokeObjectURL', { value: () => {}, configurable: true })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('useSpeech streaming queue', () => {
  it('speaks completed sentences FIFO while streaming, prefetching ahead', async () => {
    const hook = renderHook(() => useSpeech())

    // Two deltas arrive: the first completes one sentence, the second two.
    await act(async () => {
      hook.result.current.speakStream('m1', 'Uno. ', 'es')
    })
    await act(async () => {
      hook.result.current.speakStream('m1', 'Uno. Dos más. Tres', 'es')
    })
    // Both chunks fetch in order (chunk 2 begins while chunk 1 is queued for
    // playback), exactly one Audio is on the wire.
    await untilFetched(2)
    expect(ttsBodies).toEqual(['Uno.', 'Dos más.'])
    expect(audioInstances).toHaveLength(1)
    expect(hook.result.current.speakingId).toBe('m1')

    // Calling again with unchanged text is idempotent: no new fetches.
    await act(async () => {
      hook.result.current.speakStream('m1', 'Uno. Dos más. Tres', 'es')
    })
    expect(ttsBodies).toHaveLength(2)

    // The trailing fragment flushes only when the stream finishes.
    await act(async () => {
      hook.result.current.finishStream('m1')
    })
    expect(ttsBodies).toHaveLength(2)

    // Playback chains: chunk 1 ends → chunk 2 (already prefetched) plays.
    await act(async () => {
      endPlaying()
    })
    await settle()
    expect(audioInstances).toHaveLength(2)
    // Chunk 2 ends → chunk 3 ('Tres') is fetched and plays.
    await act(async () => {
      endPlaying()
    })
    await settle(40)
    expect(audioInstances).toHaveLength(3)
    await untilFetched(3)
    expect(ttsBodies[2]).toBe('Tres')
    // The queue drained → nothing is speaking anymore.
    await act(async () => {
      endPlaying()
    })
    await settle(40)
    expect(hook.result.current.speakingId).toBeNull()
    hook.unmount()
  })

  it('stop() atomically invalidates in-flight fetches and queued chunks', async () => {
    deferNext = true
    const hook = renderHook(() => useSpeech())
    await act(async () => {
      hook.result.current.speakStream('m1', 'Uno. Dos más.', 'es')
    })
    await settle(50)
    expect(deferredCalls).toHaveLength(1)

    // Stop while the first fetch is still in flight.
    await act(async () => {
      hook.result.current.stop()
    })
    await act(async () => {
      deferredCalls[0]('Uno.')
    })
    await settle(30)
    // Nothing ever plays and the second chunk is never fetched.
    expect(audioInstances).toHaveLength(0)
    expect(ttsBodies).toEqual(['Uno.'])

    // Further deltas for the stopped stream stay silent (no re-speak).
    await act(async () => {
      hook.result.current.speakStream('m1', 'Uno. Dos más. Tres.', 'es')
    })
    await settle(20)
    expect(ttsBodies).toEqual(['Uno.'])
    hook.unmount()
  })

  it('muting mid-stream clears playback; unmute applies from the next message', async () => {
    const hook = renderHook(() => useSpeech())
    await act(async () => {
      hook.result.current.speakStream('m1', 'Uno. Dos más. Bueno.', 'es')
    })
    await untilFetched(2)
    await act(async () => {
      endPlaying()
    })
    await settle()
    await act(async () => {
      hook.result.current.toggleMuted()
    })
    expect(hook.result.current.muted).toBe(true)
    await settle(30)
    // Nothing new is fetched and no chunk keeps playing.
    expect(ttsBodies).toEqual(['Uno.', 'Dos más.'])
    expect(audioInstances.every((audio) => !audio.playing)).toBe(true)

    // Growing the muted stream is dead: never re-spoken.
    await act(async () => {
      hook.result.current.speakStream('m1', 'Uno. Dos más. Bueno. Tres.', 'es')
    })
    await settle(20)
    expect(ttsBodies).toEqual(['Uno.', 'Dos más.'])

    // Unmute: the NEXT message speaks normally.
    await act(async () => {
      hook.result.current.toggleMuted()
    })
    await act(async () => {
      hook.result.current.speakStream('m2', 'Cuatro. Cinco. Adiós.', 'es')
    })
    await untilFetched(4)
    expect(ttsBodies.slice(2)).toEqual(['Cuatro.', 'Cinco.'])
    hook.unmount()
  })

  it('replay (speak) runs the full message through the same queue', async () => {
    const hook = renderHook(() => useSpeech())
    await act(async () => {
      hook.result.current.speak('m1', 'Uno. Dos. Tres.', 'es')
    })
    await untilFetched(2)
    // Chunk 1 ends → chunk 2 plays and chunk 3 is prefetched.
    await act(async () => {
      endPlaying()
    })
    await untilFetched(3)
    await settle()
    expect(ttsBodies).toEqual(['Uno.', 'Dos.', 'Tres.'])
    await act(async () => {
      endPlaying()
    })
    await act(async () => {
      endPlaying()
    })
    await settle(40)
    expect(hook.result.current.speakingId).toBeNull()
    hook.unmount()
  })
})
