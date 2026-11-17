# Quality fixes: 4 bugs + cleanup (no design items)

Scope confirmed by review thread `msg_01M7JBXN5DVB47FRH62MW7921Y`:
fix the four bugs from the code review plus the cleanup list, and remove the
onboarding "Tuning" step (answer to Q1: remove; re-add once the tutor honors it).

**Out of scope (explicitly deferred):** review items 5–11 ("Design / robustness") —
`recognition_pass → Good`, planner/grade Literals, `/sessions/end` dedupe/batching,
history trimming, `/translate` auth, `useSpeech` race guard, `fsrs_data` JSONB
shape. The POST-body conversion of `/sessions/plan|end` **is** in scope (it was
cleanup list), see Task B.

- **In (bugs):** RLS cards DELETE policy · event-loop blocking auth · onboarding
  swallowed errors · recap review-material mismatch.
- **In (cleanup):** dead schema/code · hardcoded URL in history · missing indexes ·
  POST `/sessions/plan|end` body params · `/chat` error-message hygiene · regression
  tests for fixed behavior · Tuning-step removal (write-only fields).

---

## Pinned contracts (backend Task B ↔ frontend Task C must agree)

**C1 — Session action endpoints.** `POST /sessions/plan` and `POST /sessions/end`
take a JSON body `{"session_id": "<uuid>"}` (missing → FastAPI 422). The
`?session_id=` query form is removed. Frontend callers send
`headers: {"Content-Type": "application/json", Authorization: Bearer …}` with
`body: JSON.stringify({ session_id })`.

**C2 — Recap payload.** `sessions.recap` gains
`"new_cards": [{"front": string, "back": string, "type": string}]` (empty list when
no cards were created, key always present). The recap page renders this list and
stops querying the `cards` table for "Review Material".

Both contracts live in this file; workers implement against them, and integration
verifies them end-to-end.

---

## Task A — Database migrations (independent)

**Files:** one new migration `supabase/migrations/20261116000000_quality_cleanup.sql`
(timestamp = day of merge; nothing else).

Content, in one migration, each statement guarded/commented:

```sql
-- Bug 1: the Library page deletes cards from the browser (frontend/app/library/page.tsx:74);
-- rows were silently NOT deleted because only SELECT/INSERT/UPDATE policies existed.
CREATE POLICY "Users can delete their own cards" ON cards FOR DELETE USING (auth.uid() = user_id);

-- Cleanup: dead columns (nothing in src/ or frontend/ reads any of these;
-- verified by grep at plan time).
ALTER TABLE sessions DROP COLUMN current_phase;   -- added by 20261109000001, unused
ALTER TABLE cards    DROP COLUMN state;            -- written ("new") by /sessions/end, never read
ALTER TABLE profiles DROP COLUMN preferences;      -- only writer (onboarding) removed by Task C

-- Cleanup: indexes FK-adjacent columns Postgres does not index automatically.
CREATE INDEX idx_sessions_user_id        ON sessions(user_id);
CREATE INDEX idx_sessions_user_language  ON sessions(user_id, language);
CREATE INDEX idx_transcripts_session_id  ON transcripts(session_id);
CREATE INDEX idx_cards_user_language_due ON cards(user_id, language, next_review);
CREATE INDEX idx_cards_user_created_at   ON cards(user_id, created_at);
CREATE INDEX idx_card_reviews_user_at    ON card_reviews(user_id, reviewed_at);
CREATE INDEX idx_card_reviews_session_id ON card_reviews(session_id);
```

Notes:
- Dropping columns is destructive but all three are write-only today; the local
  Supabase stack is the only deployment. If `profiles.preferences` must survive for
  old users, keep the drop but note it — nothing reads it either way.
- Migration applies at the next `task dev` / `supabase migration up`; integration
  runs that against the local stack and smoke-tests (see Integration).

**Gate:** reviewer eyeballs SQL against schema in `src/`+`frontend/` greps;
runtime check happens at integration (offline tests never touch real Postgres).

## Task B — Backend fixes (`src/voca/main.py`, `services/srs.py`, `tests/`)

1. **Event loop (bug 2).** `get_current_user` (`main.py:58`): `async def` → plain
   `def`; FastAPI runs sync dependencies in the threadpool, so the Supabase
   `auth.get_user` HTTP call (`main.py:64`) no longer freezes the loop while SSE
   streams are open. `get_owned_session` (`main.py:130`): convert to
   `async def` that fetches via `asyncio.to_thread(...)` and raises the same 404;
   the three call sites (`main.py:282/315/452`) become `await get_owned_session(...)`.
   Rationale in the task brief: every currently-running `/chat` SSE stream stalls
   whenever any request does sync auth work on the loop — this is the
   highest-impact backend change of the round.
2. **Body params (cleanup, contract C1).** Add
   `class SessionActionRequest(BaseModel): session_id: str` and use it as the body
   param of `plan_session` (`main.py:281`) and `end_session` (`main.py:313`),
   removing the query-param form. Update the `test_sessions.py` calls.
3. **Recap payload (bug 4 backend half, contract C2).** In `end_session`, before
   the final recap write: `recap["new_cards"] = [...]` from `analysis.new_cards`
   (`type/front/back`, matching C2). Keep `user_word_count` next to it.
4. **Stop writing `cards.state`** (delete the `"state": "new"` entry and its
   comment at `main.py:361-363`); Task A drops the column.
5. **`/chat` error hygiene.** Replace `yield sse({"type": "error", "message": str(exc)})`
   (`main.py:484`) with a stable client message ("The tutor hit an unexpected error.
   Please try again.") and log the exception server-side via
   `logging.getLogger("voca.main").exception(...)` (module-level `logger = …`).
   Keep the protocol shape identical (`{type:"error"}`); update tests that assert
   the leaked message, if any.
6. **Dead code: `srs.update_card_state`.** Remove the function (`srs.py:48-51`),
   its imports in `tests/test_srs.py`, and the four `test_update_card_state_*`
   tests. (`review_card_state`, `VOCA_RATING_MAP`, `new_card_state`, `next_review`
   stay.)
7. **Regression tests to add** (only behavior fixed/existing in this round):
   - `POST /sessions/plan` + `/sessions/end` with JSON body (C1); a second
     `POST /sessions/end` on a completed session → `409` (behavior already exists;
     now covered).
   - `end_session` recap payload contains `new_cards` matching the inserted cards (C2).
   - `/chat` stream error frame carries the stable message, not `str(exc)`.

**Gate:** `uv run task test` + `uv run ruff check .` — must pass in the worktree.

## Task C — Frontend fixes (5 pages)

1. **Onboarding (bug 3 + Q1 decision).** `app/onboarding/page.tsx`:
   - `completeOnboarding`: read `error` from **both** upserts
     (`const { error } = await …; if (error) throw error`) — supabase-js returns
     errors in-band, the surrounding `try/catch` alone never fires; a silent
     failure currently loops the user between `/` and `/onboarding`.
   - Remove the **Tuning step**: drop `'preferences'` from `OnboardingStep`, the
     step from the `steps` array, `correction_intensity`/`speech_speed` from
     form state/UI, and `preferences` from the profile upsert.
   - Flow: Level → Goals → **Complete Setup** (runs `completeOnboarding`); on
     success show the existing-but-currently-unreachable `complete` success view
     (its "Start Learning Now" button `router.push('/')`) instead of pushing `/`
     immediately — the success screen becomes the confirmation that the writes
     succeeded.
2. **History hardcoded URL.** `app/history/page.tsx:41`:
   `http://localhost:8000` → `BACKEND_URL` from `@/lib/api` (like every other page).
3. **Library delete assertion (bug 1 frontend half).** `app/library/page.tsx:74`:
   append `.select('id')` to the delete; if the returned rows are empty, show an
   error toast and keep the card (RLS or a vanished row now surfaces instead of
   silently "succeeding").
4. **Body params (contract C1).** `app/page.tsx`: `planSession` (`:216`) and
   `endSession` (`:406`) send `body: JSON.stringify({ session_id })` +
   `Content-Type` header; drop the `?session_id=` query string.
5. **Recap from payload (contract C2).** `app/recap/[sessionId]/page.tsx`: render
   `Review Material` from `recap.new_cards`; delete the `cards` table fetch
   (`:86-91`), the `cards` state, and the now-unused `CardRow` type. The
   empty-state copy finally matches what is shown.

**Gate:** `(cd frontend && npm run typecheck && npm run lint)` — must pass in the
worktree. No component changes beyond the five files above; no new `components/ui/*`
(hand-rolling primitives is against project convention).

---

## Subagent orchestration plan (worker model)

Shape: 3 writing children in parallel, each isolated in a managed git worktree;
then 2 read-only reviewers on the merged diff; parent does integration, gates,
and PR. Children are `subagent` builtin `worker` agents with **fresh context** —
every brief below must be pasted into the `task` (children start cold and do not
read the chat). Reviewers are `reviewer` agents, read-only, no worktree.

### Phase 0 — parent setup (no children)

1. Today's tree is clean on `main`. Create the integration branch and commit this
   plan onto it (worktree allocation **requires a clean checkout — untracked files
   count**, and the committed plan gives workers a reference):
   ```bash
   git checkout -b feature/quality-bugfixes && git add plans/quality-bugfixes.md \
     && git commit -m "docs: quality-fixes plan"
   ```
2. Dispatch requires a clean tree — verify `git status --short` is empty before
   phase 1 (the worktree machinery refuses otherwise; do not stash unless asked).

### Phase 1 — parallel implementation (one `workflow: true` call, three children)

Script embedded in the reply; `worktree: true` per child, `baseRef` pinned to the
integration branch so all three branch from the same clean point:

```js
workflow
const briefs = { migrations: "…Task A text…", backend: "…Task B text…", frontend: "…Task C text…" };
const [db, backend, frontend] = await runs.all([
  { key: "migrations", label: "Add RLS delete policy + indexes, drop dead columns",
    agent: "worker", worktree: true, baseRef: "refs/heads/feature/quality-bugfixes",
    task: briefs.migrations },
  { key: "backend", label: "Fix event-loop auth, body params, recap payload, dead code",
    agent: "worker", worktree: true, baseRef: "refs/heads/feature/quality-bugfixes",
    task: briefs.backend },
  { key: "frontend", label: "Onboarding errors + Tuning removal, BACKEND_URL, recap payload",
    agent: "worker", worktree: true, baseRef: "refs/heads/feature/quality-bugfixes",
    task: briefs.frontend },
]);
return { db: db.output, backend: backend.artifactPaths, frontend: frontend.artifactPaths };
```

Guard rails for every brief (identical preamble):
- **Authority:** touch only the listed files (A: `supabase/migrations/…` only;
  B: `src/voca/main.py`, `src/voca/services/srs.py`, `tests/*`; C: the five page
  files + nothing else). A worker that believes it needs more **stops and
  reports**, it does not expand scope.
- **Worktree:** commit inside the worktree when done (`git add -A` + a conventional
  message, e.g. `fix(db): add cards delete policy and indexes`). Do **not** push,
  do **not** touch `main`, do not spawn subagents.
- **Gates before commit:** A — none runnable offline (SQL review only); B —
  `uv run task test && uv run ruff check .`; C — `cd frontend && npm run typecheck && npm run lint`.
  Green or the child reports the failure and stops.
- **Contracts:** B and C briefs each quote C1/C2 verbatim ("the other half
  implements the same contract in parallel; do not break it; do not 'fix' it").
- **Success report:** what changed, gate output tail, files touched. Children are
  async; native completion wakes the parent — no polling.

Seam rationale: workers differ by directory (`supabase/` vs `src/voca`+`tests` vs
`frontend/app`), so merge conflicts are structurally impossible; the only coupling
is the two pinned contracts, verified at integration.

### Phase 2 — integration (parent, sequential merges)

In the main checkout: `git checkout feature/quality-bugfixes`, then merge in
branch order **A → B → C** (migrations first; they touch only SQL so order is
free, then backend, then frontend). After **each** merge run the full local gates
in the merged tree:

```bash
uv run task test && uv run ruff check . && (cd frontend && npm run typecheck && npm run lint)
```

Contract checks at the end: grep frontend calls match C1 shape; `rg new_cards`
shows both the writer (B) and the reader (C); `grep -R "localhost:8000" frontend/app`
is empty outside `lib/api.ts`. If `supabase` is running locally:
`uv run task backend`-style smoke — `supabase migration up`, then a manual
Library-delete round trip against the anon key confirms the RLS policy actually
allows deletion (offline tests cannot prove this — the fake has no RLS).

### Phase 3 — review fanout (two read-only reviewers, parallel)

After the branch is fully merged and green, one `workflow: true` call with no
worktrees (reviewers read the parent checkout, they must share the diff view):

```js
workflow
const [b, f] = await runs.all([
  { key: "review-backend", agent: "reviewer",
    task: "Review `git diff main...feature/quality-bugfixes -- src/voca tests` in /Users/lukelefebure/dev/voca against plans/quality-bugfixes.md Task B. Verify: sync→threadpool auth conversions are complete (no remaining sync Supabase calls inside async defs), contract C1/C2 implemented exactly, tests updated, no scope creep. Report findings as must-fix / nit." },
  { key: "review-frontend", agent: "reviewer",
    task: "Review `git diff main...feature/quality-bugfixes -- frontend` in /Users/lukelefebure/dev/voca against plans/quality-bugfixes.md Task C. Verify onboarding no longer writes preferences and checks upsert errors, Tuning step fully gone, recap page reads recap.new_cards (no cards query), delete asserts affected rows, no stray UI changes. Report findings as must-fix / nit." },
]);
return { backend: b.output, frontend: f.output };
```

Apply accepted findings: small fixes directly (parent), or resume the owning
retained child with the findings (`actions.resume` on its latest run id — retained
resumes keep the child's agent/context). Re-run gates after any fix.

### Phase 4 — ship

Open the PR with the `create-pr` skill (`gh` is authenticated; mirror the
conventional titles used by #1–#5, e.g. `fix(app): quality pass — RLS delete,
onboarding errors, recap payloads + cleanup`). Merge after CI; the managed
worktrees/branches are cleaned by the worktree lifecycle (handoff manifests in
each child's `artifactPaths` are the deletion authority; pass `options.handoffPath`
to `worktree cleanup` if anything is reported unknown).

### Failure recovery (from the orchestration rules)

- A rejected group dispatches **no** children — if phase 1 refuses, first check
  `git status` cleanliness, then re-verify agent names via `subagent({action:"list"})`,
  then retry the identical call once.
- A child that fails mid-flight: read `subagent({action:"status", id, view:"transcript"})`;
  the worktree keeps a patch + handoff manifest (`artifactPaths`) even for failed
  runs — capture `git -C <worktree> diff` evidence, fix forward; retry the same
  brief once, never switch CLIs to finish work.
- Contract drift discovered at integration (only seam risk): parent resolves
  **in favor of the backend (Task B is the source of truth)**, then resumes the
  frontend child with the delta.

---

## Risk / rollback

- Column drops are the only destructive step; they are all write-only columns
  verified unused, on a single-user local DB. A revert is `git revert` of the merge;
  the migration history is append-only so a new "add column back" migration would
  be needed only if data mattered — it does not here.
- The RLS policy grant is additive and can be dropped with one statement.
- If workers stall or drift badly, the round can ship as A+B only (both contracts
  are backend-anchored) with C re-planned; C2's reader and C1's caller are the only
  pieces that would then stay on old behavior (`/translate` auth is out of scope,
  so nothing breaks).

## Estimate

Children: migrations ~10 min, backend the bulk, frontend medium — wall-clock gain
comes from parallel phase 1; integration + review are the parent's serial time
(~the duration of the slowest worker). All work stays offline; no Ollama needed.
