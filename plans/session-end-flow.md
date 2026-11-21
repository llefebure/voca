# Plan: session-end-flow — an end trigger inside the input box

Branch: `feature/session-end-flow` · Worktree: `uv run task worktree:new -- feature/session-end-flow`

**Decisions (Inbox thread msg_01M7Z9WBNWRA9JDRSKM1GP159X):** restyle **only** (no
goodbye/wrap-up turn, no backend change); the restyle should be a red "stop"-style
trigger in the main chat input next to the message submit button, per review feedback.
The wrap-up concept is recorded under "Deferred ideas".

## Problem

Ending a session today looks like a destructive action rather than a chat step:

- A full-width, reddish outline bar ("End session & recap") sits permanently under the
  input box (`frontend/app/page.tsx`), styled with `destructive` tints and a flag icon —
  it reads as a warning and crowds the page.
- The confirm dialog + instant clear + recap redirect flow itself is fine; the placement
  and framing of the trigger is what's off.

## Scope

Frontend-only restyle in `frontend/app/page.tsx`. Review direction: a **red stop icon
in the main chat input box, right next to the message submit button**.

1. Remove the full-width bar entirely (the `End session & recap` `Button` under the
   `InputGroup` in the form).
2. Add the end trigger inside the same `InputGroupAddon` (block-end) as the submit
   button, immediately to its left:
   - `InputGroupButton variant="ghost"` (or `Button variant="ghost" size="icon"`) with
     the stop glyph (lucide `Square`, visually filling as a stop icon), colored
     `text-destructive`, hover `bg-destructive/10` — subtle red, not a filled danger
     block. The flag icon moves out (its "flag = end" metaphor is what read as a
     warning); the stop glyph pairs naturally with the arrow-up send button.
   - Tooltips + a11y: `title`/`aria-label` "End session & recap"; keep the
     `Tooltip` wrapper pattern used by the header buttons.
   - Visibility: only while a session is open and the tutor is quiet —
     `sessionId && !streaming` (today's bar condition). During
     `submitted`/`streaming` the trigger is hidden, so the right cluster of the input
     shows the send button (or its spinner) unambiguously.
   - Click opens the existing confirm dialog; nothing about the end flow, `/sessions/end`
     call, 409 handling, page clearing, or `/recap/<id>` navigation changes.
3. Why safe from the "send turns red while generating" confusion: in many chat UIs the
   send button *becomes* a stop button during generation. Here that never happens (the
   submit button shows a spinner, disabled), and the red trigger is hidden during
   generation — the only state where the red square is visible is a quiet conversation,
   where "stop" can only mean ending the session.
4. Discoverability tradeoff (the bar's origin): the bar was added because ending was
   the step people miss. The input-adjacent position keeps peak prominence — it sits
   next to where the eye already goes — and the tooltip names the action. If the
   discoverability problem returns, the fallback is a slim neutral text bar (ghost
   styling, no destructive tint); not built in this pass.

No backend work, no new endpoints; `use-speech`/replay behavior untouched (the
`stop()` already invoked at confirm refers to TTS playback and stays).

## Testing

- `uv run task check:frontend` (smoke renders unchanged; jsdom tests don't pin styles).
- Run `uv run task test:e2e` once in the worktree as a cheap regression pass since the
  page's form layout changes (the e2e chats and ends a session through the real UI).

## Deferred ideas (from the earlier discussion — do not build now)

- **Wrap-up turn**: on confirm, the tutor streams a short in-language goodbye (2–3
  sentences referencing a plan objective) via a new `POST /sessions/wrap-up`, spoken via
  TTS, then archive + navigate. Rejected for now (person chose restyle only); revisit if
  endings still feel abrupt after this pass.
- **Inline recap sheet** over the chat instead of navigating to `/recap` (duplicates the
  recap page; rejected).
- **Tutor detects "wrapping up" from the chat itself** (fragile heuristics; rejected).

## Notes

- Both this and `plans/streaming-tts.md` touch `frontend/app/page.tsx`, but with this
  scope the overlap is only near the input/speak regions; manual merge is trivial either
  order.
