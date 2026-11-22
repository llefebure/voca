'use client'

import * as React from 'react'

const MUTED_STORAGE_KEY = 'voca-tts-muted'

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
 * Speech playback for tutor messages: auto-speaks each finished reply (unless
 * muted), can replay a specific message, and stops whatever is playing.
 * Audio streams through the /api/tts proxy and plays via an `Audio` element;
 * the target language selects the model/voice (see lib/languages.ts).
 */
export function useSpeech() {
  // Read localStorage through useSyncExternalStore so no server/client branch
  // taints the hydrated HTML: React hydrates with the server snapshot
  // (unmuted) and re-renders with the persisted value afterwards — a localStorage
  // read in a state initializer would instead render a different icon client-
  // side on the first pass (hydration mismatch on the mute button).
  const muted = React.useSyncExternalStore(subscribeMuted, readMutedSnapshot, () => false)
  const [speakingId, setSpeakingId] = React.useState<string | null>(null)
  const audioRef = React.useRef<HTMLAudioElement | null>(null)
  const urlRef = React.useRef<string | null>(null)

  const stop = React.useCallback(() => {
    audioRef.current?.pause()
    audioRef.current = null
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current)
      urlRef.current = null
    }
    setSpeakingId(null)
  }, [])

  const speak = React.useCallback(
    async (id: string, text: string, lang?: string) => {
      if (muted || !text.trim()) return
      stop()
      try {
        const response = await fetch('/api/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, lang }),
        })
        if (!response.ok) return
        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        const audio = new Audio(url)
        audioRef.current = audio
        urlRef.current = url
        setSpeakingId(id)
        audio.onended = () => {
          if (audioRef.current === audio) stop()
        }
        await audio.play()
      } catch {
        // Autoplay restrictions or a network hiccup: stay silent.
      }
    },
    [muted, stop],
  )

  const toggleMuted = React.useCallback(() => {
    const next = !readMutedSnapshot()
    window.localStorage.setItem(MUTED_STORAGE_KEY, next ? '1' : '0')
    if (next) stop()
    for (const listener of mutedListeners) listener()
  }, [stop])

  React.useEffect(() => stop, [stop])

  return { muted, toggleMuted, speakingId, speak, stop }
}
