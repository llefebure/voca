# Plan: streaming-tts — speak as the tutor writes, sentence by sentence

Branch: `feature/streaming-tts` · Worktree: `uv run task worktree:new -- feature/streaming-tts`

## Problem

Speech starts only after the tutor's reply has **fully streamed** (`status === 'ready'`
effect in `frontend/app/page.tsx`), and then waits for the **entire WAV** to be generated
by `/api/tts` (frontend/app/api/tts/route.ts proxies Ollama `/v1/audio/speech` in one
body; `lib/use-speech.ts` awaits the blob before play). Perceived latency = full reply
generation + full TTS synthesis before the first word is heard.

Goal: buffer the streaming text, cut it at punctuation, and send sentences to TTS while
the tutor is still typing — first sentence plays within a couple of seconds.

## Approach — client-side sentence queue (no backend change)

Ollama's speech endpoint returns a WAV per request; chunking client-side and queueing
playback ships the same UX as a server-side audio pipeline with far less risk.

### 1. Pure text piece: `frontend/lib/speech-chunk.ts` (new)

- `splitSpeechChunk(text: string): string` — returns completed leading sentences,
  boundaries on `.`, `!`, `?`, `…`, newline (and `;` for Spanish long clauses is
  *not* a stop — keep reading). Only split when whitespace follows the punctuation
  (avoids "1.5", "Sr."), plus a hard cap: if the buffer exceeds ~220 chars with no
  boundary, cut at the last space (a rambling clauseless sentence still gets spoken).
  Remember the Spanish openers (`¡`, `¿`) need nothing special: splitting happens on the
  *closing* mark that follows them.
- `stripForSpeech(text: string): string` — the tutor streams Markdown: strip code
  fences/blocks, headings, emphasis markers, list bullets, images/links (keep link
  text). Unit-test both functions hard (Vitest): abbreviations, decimals, ellipses,
  inverted marks, mixed markdown.

### 2. Queue: extend `frontend/lib/use-speech.ts`

- Keep `speak(id, text, lang)` for full-message replay, but implement it over the same
  queue so replay speaks in chunks too.
- New streaming ops used by the chat page:
  - `speakStream(id, fullTextSoFar)` — idempotent per (id, grown text): takes the
    accumulated assistant text, strips it for speech, feeds any newly-completed
    sentences into the queue. The page decides when to call it (below).
  - `finishStream(id)` — flush any trailing fragment as a final chunk.
- Internals: a per-message FIFO of sentence strings; **prefetch**: while chunk N plays,
  chunk N+1's TTS request is already in flight (serialize fetches, 1 in flight, to avoid
  hammering local Ollama; still plenty — fetch ≪ playback). Playback: chained `Audio`
  elements (`onended` → next) or one persistent element fed per-chunk object URLs. A
  generation token per message id so `stop()` invalidates all in-flight fetches and
  queued chunks atomically.
- Interaction rules (match today's UX): the mute toggle stops playback and clears the
  queue; starting a new speak/stop resets it; unmuting mid-message takes effect on the
  next message (no retroactive speech); errors in one chunk are skipped silently after a
  bounded retry, playback continues with the next sentence.

### 3. Wire-up in `frontend/app/page.tsx`

- Replace the speak-on-ready effect: while `status === 'streaming'` (and `status ===
  'ready'` once), call `speakStream(lastAssistantId, currentText)` on each message
  update for the last assistant message; when streaming ends call `finishStream`.
  `lastSpokenRef` logic collapses into the per-stream idempotency guard (a stream whose
  turn was already consumed — e.g. restored history — must not re-speak).
- Keep the per-message replay/stop buttons working against the queue.

## Tests

- `frontend/tests/speech-chunk.test.ts` (new): the splitter and stripper tables above.
- A queue-level unit test with mocked fetch/Audio: order preserved across interleaved
  deltas, stop() kills in-flight work, mute mid-stream clears.
- `pages-smoke.test.tsx` unaffected (fetch is already mocked in tests/helpers; the smoke
  suite must stay offline/green).
- E2E `uv run task test:e2e` (worktree dev up): chat reply still renders and no uncaught
  errors; audio is exercised lightly (autoplay policies vary — playback failures are
  already swallowed silently, keep it that way).

## Risks / notes

- Inter-sentence gap: chained Audio elements can click/gap slightly between chunks —
  acceptable v1; a Web-Audio scheduled variant is the noted follow-up if it bothers.
- Ollama `/v1/audio/speech` semantics are "request → complete WAV"; if it ever rejects
  very short inputs, guard by not enqueueing empty/one-glyph sentences (merge into next).
- **Coordination with session-end-flow**: both touch `page.tsx`, different regions
  (speak effect vs end flow). This branch lands first is preferable, but either order
  merges by hand with no semantic conflict.

## Gates

`uv run task check:frontend`, `uv run task test:e2e` with `uv run task dev` in the
worktree (no backend change; backend gates untouched).
