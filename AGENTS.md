# Voca — agent guide

AI-powered Spanish learning app: conversational tutor (streaming chat + TTS), SRS review cards (FSRS), session planning/recap agents on top of Postgres via Supabase.

## Stack

- **Backend** `src/voca/` — Python 3.14, FastAPI + `pydantic-ai`, served by uvicorn. LLM runs on local **Ollama** (OpenAI-compat API): chat `granite4.2:3b` (settings in `services/llm.py`, reasoning disabled), TTS `phonon:40m-es` (Spanish voice "Alicia", `POST /v1/audio/speech` → WAV).
- **Frontend** `frontend/` — Next.js 16 (App Router), Tailwind v4, shadcn **base-nova** style on **Base UI** (`@base-ui/react`, *not* Radix; `toast` from `ui/toast`, `cn` from the `cn` package). Components come from the shadcn CLI — never hand-roll a `components/ui/` primitive. Next 16 differs from older knowledge: read the warning in `frontend/AGENTS.md` and its docs under `frontend/node_modules/next/dist/docs/` before writing Next code.
- **DB/Auth** — Supabase, run locally (`supabase/` migrations). Postgres tables: `profiles`, `sessions` (+`plan`, `recap`), `transcripts`, `cards` (FSRS state in `fsrs_data`, `next_review`), `lessons`. Backend uses the service-role key; the browser uses the anon key with RLS.
- **SRS** — `services/srs.py` wraps the `fsrs` package (`Scheduler.review_card(card, rating, when) -> (Card, ReviewLog)`); rating map in `VOCA_RATING_MAP`.

## Commands (Taskfile, run with `uv run task <name>`)

```bash
uv run task dev          # supabase start + migrate, then backend (uvicorn, :8000) + frontend (next dev, :3000)
uv run task backend      # backend only          uv run task frontend   # frontend only
uv run task test         # pytest, offline/deterministic (mocked supabase, pydantic-ai TestModel). Always green without Ollama/Supabase.
uv run task test:all     # also runs live-LLM integration tests (marker `integration`; needs Ollama up)
uv run task tidy         # ruff lint --fix + format (backend)
(cd frontend && npm run typecheck && npm run lint)   # frontend gate, also `uv run task check:frontend`
```

Env: `src/voca/.env` (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `LLM_BASE_URL`) and `frontend/.env.local` (`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_URL` anon key). Ollama must be running at `http://localhost:11434`.

## Layout

```
src/voca/
  main.py            # FastAPI app: /health, /chat (SSE), /sessions/*, /translate, /ollama/health
  agents/            # pydantic-ai agents: tutor_agent (chat), session_planner_agent (/sessions/plan),
                     # post_session_agent (/sessions/end → cards, recap, profile)
  services/          # llm.py (Ollama model), supabase_client.py, srs.py (FSRS)
frontend/
  app/page.tsx       # chat (the main page); app/api/chat/route.ts proxies /chat; app/api/tts/route.ts
  components/ui/     # shadcn base-nova primitives (Base UI); chat primitives: message, bubble, message-scroller
  lib/               # api.ts (backend/ollama config), supabase.ts, use-speech.ts (TTS hook)
supabase/migrations/ # schema; tests/  # pytest suite (offline by default)
```

## Conventions

- Backend imports are package-absolute (`from voca.services.srs import …`); serve with `uv run uvicorn voca.main:app`.
- `/chat` is SSE: each event is a single-line JSON `{type: "delta"|"error"|"done", …}` on `data:`.
- Frontend talks to the backend through `lib/api.ts` constants; auth = Supabase JWT in `Authorization: Bearer`.
- After backend or frontend changes: run `uv run task test`, `uv run ruff check .`, and the frontend typecheck/lint — **fix breakage before claiming done**.
