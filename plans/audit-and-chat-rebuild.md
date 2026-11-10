# Voca: Fix Broken Refactor, Clean Chat UI + TTS, AGENTS.md, Test Suite

## Context

The last commits (`c041fe4` "UI refactor", `333b3bb` "fix agent interface") plus an uncommitted
working-tree change left the app in a broken, half-finished state:

- `frontend/app/page.tsx` **does not compile** (5 syntax errors, stray `</div>`, TODO comments
  left in code). `next dev` on :3000 serves a 500.
- The frontend chat stack is fake/hand-rolled: `components/ui/{message,bubble,message-scroller,input-group,empty,trace}.tsx`
  are knockoffs of the real shadcn `base-nova` chat primitives (project uses `style: "base-nova"`,
  `@base-ui/react` — Base UI, per `components.json`).
- `useChat` from `@ai-sdk/react` is wired against a backend protocol it doesn't speak: FastAPI emits
  raw token deltas (`data: <token>\n\n`), the AI SDK expects its UI Message Stream JSON protocol.
  The input box is bound to a dead `draft` state; submit never actually sends a message.
- No TTS exists anywhere.
- Backend has real correctness bugs (SSE framing, SRS ratings, missing imports, debug logging).
- Test suite fails **4/4** and is not safe for agents to rely on (live Ollama dependency, brittle
  assertions, stale imports).

Goals from the owner:
1. Write a proper root `AGENTS.md` (brief, high-value).
2. Clean chat UI using Base UI defaults from shadcn (real `base-nova` chat primitives).
3. Chat = simple back-and-forth with `spanish_tutor` only (other agents later).
4. Speak tutor outputs via TTS: Ollama `phonon:40m-es` running locally.
5. Code review everything (junior codebase) — fix findings.
6. Proper test suite; instruct agents to run tests before claiming done.

## Audit Findings (what's actually broken)

### Frontend
- `app/page.tsx`: syntax errors, non-compiling; `useChat` misintegration (see Context); dead state;
  non-functional buttons (translate/replay/slow-down are stubs; "Reset session" button has a Volume2
  icon and calls nothing); `MotionMessageScrollerItem` re-created every render.
- Knockoff UI components to be replaced by real registry versions: `message.tsx`, `bubble.tsx`,
  `message-scroller.tsx`, `input-group.tsx`, `empty.tsx`, `trace.tsx` (also `code-block.tsx`).
  Real `button`, `toast`, `tooltip`, `dialog`, etc. (Base UI style) are legit — keep.
- `app/api/chat/route.ts` proxy exists but is orphaned: `page.tsx` points `useChat` directly at
  `http://localhost:8000/chat` (CORS + no auth header). Route has correct idea (forward auth,
  create session, map history) but wrong protocol (passes raw SSE through to `useChat`).
- Backend base URL hardcoded `http://localhost:8000` in several pages — fine for now; standardize
  into one constant.
- `lib/utils.ts` uses the `cn` package (shadcn-official, correct for base-nova — keep).

### Backend (`src/voca/main.py`, services, agents)
- `main.py`: `os.getenv` used in `/ollama/health` but **`import os` is missing** → NameError.
- `/chat` SSE framing is broken: `yield f"data: {delta}\n\n"` — any delta containing a newline
  corrupts the stream. Deltas must be JSON-encoded; error/done markers as structured JSON.
- `/chat`: `import asyncio` buried inside function; `print(f"DEBUG: …")` noise on every token;
  user transcript row saved via `BackgroundTasks` even on stream error (lost-message risk is minor).
- `services/srs.py`: `update_card_state()` **constructs a `ReviewLog` it never uses and calls**
  `self.fSRS.repeat(card, now)` — **`Scheduler.repeat` does not exist** (installed fsrs API is
  `review_card(card, rating, when) -> (Card, ReviewLog)`), and the `rating` argument is **ignored**.
  Every graded card would crash or mis-schedule. Also `recognition_pass` maps to `Good` while the
  docstring says `Easy`; whole file is littered with confusion comments.
- `main.py /sessions/end`: inserts new cards with `"state": create_new_card_state()` — writes a FSRS
  JSON blob into the `state TEXT DEFAULT 'new'` column (schema intends state label 'new'); then
  queries graded/due cards with `.eq("state", "new")`, which after that insert no longer matches
  anything meaningful. Fix: keep `state` a label ('new'), store FSRS state in `fsrs_data` (which the
  code already reads back), and select due cards by `next_review <= now` instead of `state = 'new'`.
- `services/llm.py`: unconditional request-body logger hook on every LLM call (noisy, logs full
  prompts); `extra_body={"think": False}` **does not work** through the OpenAI-compat endpoint
  (verified: granite still returns `reasoning`). `reasoning_effort: "none"` works (verified: 11
  completion tokens vs 2,900+ with reasoning) → 10-100x faster chat turns.
- `main.py` CORS: `allow_origins=["*"]` + `allow_credentials=True` — tighten to localhost origins.
- Module imports are path-dependent (`from agents…`, `from services…` require
  `PYTHONPATH=src/voca`, only set in Taskfile tests). `voca` is an installed package (uv editable
  install works: `import voca` OK from repo root) → standardize on `voca.…` imports and
  `uv run uvicorn voca.main:app`.
- `main.py` module-level `supabase` import crashes at import time if env missing — tests handle via
  envs; keep but make test envs explicit.
- Dead code: `ChatResponse`/`SessionResponse` unused fields, stale `plans/simplify-tutor-streaming.md`
  is checked off but only partially true.

### Tests
- `tests/test_agents.py`: all 4 fail. Tutor tests expect removed `TutorResponse` model; post-session
  test builds transcript with `role`/`content` keys but the agent's instruction builder expects
  `speaker`/`text` (matches the DB); planner test asserts exact lesson id (LLM-guessed, brittle).
- `tests/conftest.py`: httpx request/response logger fixture (debug scaffolding) — should go.
- Tests hit live Ollama (`granite4.2:3b`) — slow (~105s) and nondeterministic.
- No tests for `/chat` SSE, SRS unit behavior, or any HTTP endpoint.

### Infra / docs
- Root `AGENTS.md` is a stale feature spec (agent descriptions), not agent navigation info.
- `frontend/AGENTS.md` contains the auto-managed Next.js 16 version warning (keep it).
- No typecheck/lint/test entry points documented for agents. Frontend has no `typecheck` script.

## Approach

1. **Root `AGENTS.md`** — brief navigation doc (stack, commands, layout, conventions, test
   instructions). Link `frontend/AGENTS.md` for the Next.js warning.
2. **Backend fixes** (keep the streaming refactor; fix its bugs):
   - JSON-encode SSE deltas; structured `{type: "delta"|"error"|"done"}` events; move `import
     asyncio`; drop `print` debug logs; fix `import os`; CORS → localhost; tighten transcript saves.
   - `llm.py`: `reasoning_effort: none`, env-gated request logging, remove `httpx2` deprecation
     noise where possible.
   - `srs.py`: use `Scheduler.review_card(card, rating, now)`; restore `recognition_pass → Easy`;
     clean comments; unit-testable pure functions.
   - `/sessions/end`: fix `state` vs `fsrs_data` semantics, select by `next_review`.
   - Standardize `voca.*` imports + `uv run uvicorn voca.main:app` entrypoint (owner-confirmed).
3. **Frontend chat rebuild** (the core deliverable):
   - Install the real chat primitives: `npx shadcn@latest add message-scroller message bubble
     input-group empty spinner attachment marker trace code-block` (pulls `@shadcn/react` dep).
     Delete the knockoff files it replaces.
   - Data flow (owner-confirmed): `app/api/chat/route.ts` = the single proxy — reads Supabase
     bearer from request, lazily creates the session via backend `/sessions/start` (returns id in
     `x-voca-session` response header), maps the last user message + history, forwards to backend
     `/chat`, and transcodes the SSE token stream into the AI SDK UI Message Stream with
     `createUIMessageStream`. Client page uses `useChat` (`messages`, `sendMessage`, `status`).
   - Chat page: `MessageScrollerProvider(autoScroll)` > `MessageScroller` > `Viewport` >
     `Content` > `MessageScrollerItem(scrollAnchor on user)` > `Message` > `Bubble` > `BubbleContent`
     (assistant text rendered with existing `Markdown`); prompt is a real `InputGroup` with
     `InputGroupTextarea` + `InputGroupAddon` send button using `InputGroupButton`; `useChat`
     `status` → `Spinner` on send button, `shimmer` "thinking" text; real `Empty` state; functional
     translate (existing `/translate`), reset session (new session id + `setMessages([])`).
   - **TTS**: `app/api/tts/route.ts` proxies `POST /v1/audio/speech` to local Ollama
     (`model: phonon:40m-es`, `voice: "Alicia"`, 24 kHz PCM WAV), avoiding browser CORS. A small
     `useSpeech` hook plays each completed tutor reply via an `Audio` element (objectURL), keeps a
     mute toggle (persisted), a play/replay button on assistant messages, and stops audio when a new
     reply starts streaming. Voice/model live in one config constant in `frontend/lib/api.ts`.
   - **End of session (owner-confirmed: include now)**: an "End session" control in the chat header
     (behind a confirmation, stops any playing audio first) calls backend `/sessions/end` directly
     with the bearer token (the only non-stream direct call; CORS fix covers it), then navigates to
     the existing `/recap/[sessionId]` page, which already reads `sessions.recap` + latest cards
     under RLS. After ending, `sessionId` resets so the next message starts a fresh session.
4. **Test suite** (offline, deterministic):
   - `conftest.py`: replace logger fixture with a Supabase mock factory + env fixtures.
   - Agent tests: pydantic-ai `TestModel` via `agent.override(model=TestModel())` (per the
     `building-pydantic-ai-agents` skill) — no LLM needed. Optional opt-in live Ollama tests behind
     a `@pytest.mark.integration` marker + `-m "not integration"` default.
   - New: `test_srs.py` (FSRS update math), `test_chat.py` (SSE framing w/ FastAPI `TestClient`,
     mocked agent run + supabase), `test_sessions.py` (`/sessions/start|end` card flows), maybe
     `test_health.py`.
   - Frontend gate: `tsc --noEmit` + `eslint` scripts; run in Taskfile.
   - Taskfile: `test` (offline pytest), `test:all`, `lint:frontend`, `typecheck`.
   - `AGENTS.md` instructs: run backend tests + typecheck before claiming done.
5. Leave `session_planner`/`post_session` agents and non-chat pages untouched (chat scope), minus
   the correctness fixes above.

## Files to modify

- `AGENTS.md` (root, rewrite)
- `src/voca/main.py` — imports, SSE framing, CORS, logger cleanup, os fix, sessions/end fixes
- `src/voca/services/llm.py` — reasoning_effort, logging gate
- `src/voca/services/srs.py` — rewrite update path
- `src/voca/agents/*.py` — import path fixes; tutor prompt kept
- `tests/conftest.py`, `tests/test_agents.py`, new `tests/test_srs.py`, `tests/test_chat.py`,
  `tests/test_sessions.py`
- `pyproject.toml` — pytest-asyncio loop scope config, markers
- `Taskfile.yml` — test/typecheck/lint targets
- `frontend/app/page.tsx` — full rebuild
- `frontend/app/api/chat/route.ts` — rewrite as SSE→UIMessage transcoder (+ session lazy-create)
- `frontend/app/api/tts/route.ts` — new
- `frontend/lib/` — `api.ts` (base URLs/config: backend URL, TTS model/voice), `use-speech.ts` hook
- `frontend/app/recap/[sessionId]/page.tsx` — check/patch so it renders `/sessions/end` output as-is
- `frontend/components/ui/{message,bubble,message-scroller,input-group,empty,trace,code-block}.tsx`
  — deleted (replaced by registry versions)
- `frontend/components/` — added registry files (via CLI)
- `frontend/package.json` — `typecheck` script, `@shadcn/react` dep (auto via CLI)

## Reuse

- Real chat primitives via shadcn CLI + rules in `.agents/skills/shadcn/rules/chat.md` (composition
  guide I will follow exactly).
- `frontend/lib/supabase.ts`, `DashboardLayout`, `Sidebar`, `ThemeToggle`, `Markdown`,
  real `Button/Toast/Tooltip/DropdownMenu` — all keep.
- `pydantic_ai.models.test.TestModel` + `agent.override()` for offline agent tests.
- FastAPI `TestClient` + `asyncio.to_thread`-mocked supabase for endpoint tests.
- Existing `/translate` endpoint for the translate button; `/sessions/start` for lazy session.
- Ollama TTS: `POST http://localhost:11434/v1/audio/speech {model: "phonon:40m-es", input, voice?}`
  → 24 kHz mono 16-bit PCM WAV (verified live). Available voices (verified): Alba, Aldo, Alicia,
  Azucena, Borja, Candela, Celia, Danae, Guillermo, Iker, Izan, Jimena, Lalo, Leonel, Lucía-Sol,
  Marcos, Nerea, Nico, Noa, Nuno, Rebeca, Regina, Ulises, Ximena, Yael, default. ("Zoey" from the
  example does not exist for this Spanish model.)
- `reasoning_effort: "none"` verified working on granite4.2:3b via OpenAI-compat.

## Steps

- [x] Write root `AGENTS.md`
- [x] Backend: `llm.py` (reasoning off, logging gate), `srs.py` (review_card), `main.py` fixes
      (os import, SSE JSON framing, CORS, asyncio import, debug prints, sessions/end state fix)
- [x] Backend: standardize imports + `uvicorn voca.main:app` entrypoint
- [x] Frontend: install real chat components via CLI; remove knockoffs
- [x] Frontend: `/api/chat` route proxy + transcoder; `/api/tts` route
- [x] Frontend: rebuild `app/page.tsx` with useChat + MessageScroller composition + TTS hook
- [x] Frontend: "End session" control in chat header → `/sessions/end` → `/recap/[sessionId]`
      (stop audio, reset sessionId; verify recap page reads the ended session correctly)
- [x] Tests: conftest, agent (TestModel), srs, chat SSE, sessions; Taskfile + pyproject config
- [x] Frontend: typecheck/lint scripts; Taskfile targets
- [x] Run full verification (below), fix fallout
- [x] Update plan notes, commit in logical chunks

## Verification

- Backend: `uv run task test` (all green, offline; live tests opt-in), `uv run ruff check .`
- Frontend: `npm run typecheck`, `npm run lint`, `npm run build` in `frontend/`
- E2E manual (servers via `uv run task dev`):
  1. Sign in at :3000 (`/auth`), land on chat, empty state shows.
  2. Send "Hola" → token stream renders in Bubble; assistant reply auto-speaks (audible WAV);
     mute toggle stops autoplay; replay button re-speaks a message.
  3. Multi-turn exchange persists to Supabase `transcripts`; refresh → same session messages
     (history sent so tutor has context).
  4. Newline-heavy reply (ask tutor for multi-line) → stream stays intact (framing fix).
  5. Translate button returns a toast translation.
  6. "End session": confirm dialog → session marked completed, cards/recap generated (check the
     session row + cards in Supabase), land on `/recap/[sessionId]` showing the recap; next message
     from the chat starts a new session id.
  7. `curl localhost:8000/ollama/health` no longer 500s.
- Tests + typecheck re-run before claiming done (instruction goes in AGENTS.md).

## Decisions (owner-confirmed via Inbox 2026-01-10)

1. Chat data flow: **Next.js proxy route + AI SDK `useChat`**.
2. TTS: **auto-speak each tutor reply + persisted global mute toggle + per-message replay**.
3. Voice: **Alicia** (`phonon:40m-es`).
4. Audit scope: **backend correctness set + latency (reasoning off) + import cleanup + debug-flag
   removal — all included**.
5. End-of-session: **include now** — "End session" button wired to `/sessions/end`, linking to the
   recap page.
