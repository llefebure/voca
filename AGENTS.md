# Voca — agent guide

AI-powered language learning app (interface English; target language selectable, Spanish only today): one continuous tutor conversation (streaming chat + TTS) with a canvas panel the tutor drives via a tool, SRS review cards (FSRS), a session-end analyst, Postgres via Supabase.

## Stack

- **Backend** `src/voca/` — Python 3.14, FastAPI + `pydantic-ai`, served by uvicorn. LLM runs on **Ollama** (OpenAI-compat API); one model lane: every agent — the streaming tutor included — is `gemma4:31b-cloud` via `LLM_MODEL` (cloud: needs `ollama signin`). One conversation per session, no phase machine: the tutor converses and calls `show_panel`/`hide_panel` (`agents/tutor_agent.py`) whenever structured content helps — the UI pops a canvas panel on the right (split view). Panel content is the typed block primitives in `services/panel_content.py` (scenario/text/dialogue/questions/tasks/word_bank), normalized/validated defensively. `/chat` streams SSE frames `{type: "delta"|"status"|"event", ...}` — panel events are typed data parts on the frontend and persist in `transcripts.payload` for restore (panel state replays from payload rows, not a session column). At session end the analyst (`agents/post_session_agent.py`) applies the FSRS rubric (recall woven into the outcome definitions; `services/srs.py` `VOCA_RATING_MAP`), harvests new cards, and writes the recap. Target language lives in `profiles.target_language`; supported languages map in `services/languages.py`. TTS `POST /v1/audio/speech` → WAV, model/voice resolved per language (today `phonon:40m-es` / "Alicia").
- **Frontend** `frontend/` — Next.js 16 (App Router), Tailwind v4, shadcn **base-nova** style on **Base UI** (`@base-ui/react`, *not* Radix; `toast` from `ui/toast`, `cn` from the `cn` package). Components come from the shadcn CLI — never hand-roll a `components/ui/` primitive. Next 16 differs from older knowledge: read the warning in `frontend/AGENTS.md` and its docs under `frontend/node_modules/next/dist/docs/` before writing Next code.
- **DB/Auth** — Supabase, run locally (`supabase/` migrations). Postgres tables: `profiles` (+`target_language`), `sessions` (+`recap`), `transcripts` (+`payload` — panel events replay from here), `cards` (FSRS state in `fsrs_data`, `next_review`), `card_reviews`. Backend uses the service-role key; the browser uses the anon key with RLS.
- **SRS** — `services/srs.py` wraps the `fsrs` package (`Scheduler.review_card(card, rating, when) -> (Card, ReviewLog)`); rating map in `VOCA_RATING_MAP`.

## Commands (Taskfile, run with `uv run task <name>`)

```bash
uv run task dev          # supabase start + migrate, ensure the always-working test login, then backend (uvicorn, :8000) + frontend (next dev, :3000)
uv run task backend      # backend only          uv run task frontend   # frontend only
uv run task test         # pytest, offline/deterministic (mocked supabase, pydantic-ai TestModel). Always green without Ollama/Supabase.
uv run task test:all     # also runs live-LLM integration tests (marker `integration`; needs Ollama up)
uv run task tidy         # ruff lint --fix + format (backend)
uv run task check:frontend  # frontend gate: typecheck + lint + unit tests (Vitest, offline, supabase mocked)
uv run task test:e2e     # Playwright browser smoke — NOT part of the gate; needs `uv run task dev` up. CANONICAL (and only supported) invocation: don't run `npx playwright test` directly — extra args pass through, e.g. `uv run task test:e2e -- -g progress` or `-- --ui`
uv run task check        # every automated gate: test + lint + check:frontend
```

Env: `src/voca/.env` (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `LLM_BASE_URL`, `LLM_MODEL`) and `frontend/.env.local` (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`). Ollama must be running at `http://localhost:11434` and signed in for cloud models.

## Layout

```
src/voca/
  main.py            # FastAPI app: /health, /chat (SSE), /sessions/*, /translate, /ollama/health
  agents/            # pydantic-ai agents: tutor_agent (chat + show_panel/hide_panel tools),
                     # post_session_agent (/sessions/end: FSRS rubric, new cards, recap)
  services/          # llm.py (one model lane), panel_content.py (typed panel blocks),
                     # languages.py, srs.py, supabase_client.py
frontend/
  app/page.tsx       # chat (the main page): one conversation + canvas (split view while a panel
                     # shows; collapsed panel records in the thread); app/api/chat/route.ts proxies
                     # /chat into AI-SDK data parts; app/api/tts/route.ts (voice)
  components/panel/  # panel canvas (split view), panel records, block rendering per type
  components/ui/     # shadcn base-nova primitives (Base UI); chat primitives: message, bubble, message-scroller
  lib/               # panel-events.ts (typed stream payloads + panel types),
                     # languages.ts (language map + TTS per language), api.ts, supabase.ts, use-speech.ts
supabase/migrations/ # schema; tests/  # pytest suite (offline by default)
frontend/tests/      # Vitest + RTL suite (offline: supabase + backend fetch mocked in
                     # tests/helpers/); pages-smoke.test.tsx smoke-renders every route;
                     # frontend/e2e/ # Playwright browser smoke (auth.setup.mjs seeds the test user,
                     # smoke.spec.mjs visits each route and fails on uncaught page errors)
```

## Conventions

- Backend imports are package-absolute (`from voca.services.srs import …`); serve with `uv run uvicorn voca.main:app`.
- `/chat` is SSE: each event is a single-line JSON `{type: "delta"|"error"|"done", …}` on `data:`.
- Frontend talks to the backend through `lib/api.ts` constants (language names + TTS config in `lib/languages.ts`); auth = Supabase JWT in `Authorization: Bearer`.
- After backend or frontend changes: run `uv run task test`, `uv run ruff check .`, and `uv run task check:frontend` — **fix breakage before claiming done**. Frontend pages have jsdom smoke tests precisely because typecheck/eslint miss runtime UI breakage (provider misuse, hydration/undefined-data crashes); when adding a page or component, extend `frontend/tests/` (see `tests/helpers/supabase-mock.ts` for the canned-data pattern).
- When touching something only the real browser catches (hydration, real Supabase wiring), also run the browser smoke via `uv run task test:e2e` with `uv run task dev` up — always through the task, never bare `npx playwright test` (the task is what exports the seeder's env). The E2E suite self-seeds its test user (`e2e-test@voca.local` / `voca-e2e-password-1`) into local Supabase — and every `uv run task dev` re-ensures that same login first (via `ensure-dev-user`), so it always works on a fresh/stack-reset database.
- Plan documents live in `plans/` (e.g. `plans/<short-name>.md`), never at the repo root — one file per plan, same filename across revisions.
- Do the work on a dedicated feature branch cut from `main` (e.g. `feature/<short-name>`, or `fix/<short-name>` for bug fixes); do not commit directly to `main`.

## Parallel agents in git worktrees (Supabase stack mode)

Supabase runs with `experimental.stack = true` (in `supabase/config.toml`): every git worktree/branch gets its own local Supabase project — own containers, auto-assigned stable ports, own DB and migration history, own keys. No port or data collisions across parallel agents.

- `uv run task worktree:new -- feature/<short-name>` — creates `.worktrees/<name>` (from `main`), installs deps, starts its own stack, writes per-worktree env files (`src/voca/.env`, `frontend/.env.local`, `.worktree.env` with the worktree's frontend/backend ports).
- `uv run task worktree:remove -- <short-name>` — stops its stack, removes the dir; leftover stack data: `supabase stack list` + `supabase stack destroy --stack-id <id> --yes`.
- Inside a worktree run the same tasks (`uv run task dev`, `test`, `check`, `test:e2e`) — dev-server ports (frontend 11xxx, backend 11xxx by default; overridable via `.worktree.env`) and Supabase URL/keys resolve per worktree.
- `uv run task env:sync` regenerates a checkout's env files from its stack (run after first-ever stack-mode start, or when keys change).
- `supabase stack list` shows every stack on the machine; stack-mode identity = worktree path + git branch.
- Legacy stacks started before stack mode keep running until stopped with `SUPABASE_EXPERIMENTAL_STACK=0 supabase stop`.
