"""Voca FastAPI backend.

One continuous conversation per session, with a canvas: the tutor agent calls
`show_panel` and the UI pops the content on the right (split view). Chat is
streamed as Server-Sent Events with single-line JSON frames:
`data: {"type":"delta","text":...}` for chat text, `{"type":"status","text":...}`
for transient chips, `{"type":"event","kind":...,"data":...}` for structured UI
events (`panel_shown`/`panel_hidden`), and `{"type":"done"}` (or
`{"type":"error"}`), so newlines inside payloads cannot corrupt the stream.
At session end, an analyst applies the FSRS rubric to the transcript and writes
new cards + recap. Serve this app with `uv run uvicorn voca.main:app` from the
repository root.
"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from postgrest.exceptions import APIError
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

from voca.agents.post_session_agent import CardCandidate, post_session_agent
from voca.agents.tutor_agent import (
    TutorDeps,
    execute_leaked,
    parse_tool_leak,
    tutor_agent,
)
from voca.services.languages import DEFAULT_LANGUAGE
from voca.services.llm import LLM_BASE_URL, voca_model
from voca.services.srs import (
    VOCA_RATING_MAP,
    new_card_state,
    next_review,
    review_card_state,
)
from voca.services.supabase_client import supabase
from voca.services.telemetry import configure_telemetry

load_dotenv()

# How much of the streamed tail may still be forming a leaked tool call
# (`<tool_code>` head, `call:<name>`): hidden until it resolves into a span.
_LEAK_HOLD = 24
# Above this a markerless tail is presumed prose and flushed; a tail holding an
# open tool-call marker (`call:show_panel{...blocks...}` can be very large)
# is never flushed past the marker.
_LEAK_PASSTHROUGH_CAP = 4000

app = FastAPI(title="Voca Backend")

# Logfire: FastAPI requests, outgoing httpx calls, and Pydantic AI agent runs.
configure_telemetry(app)

logger = logging.getLogger("voca.main")

# The Next.js dev/prod frontend is the only browser client we expect.
_allowed_origins = os.getenv(
    "VOCA_FRONTEND_URLS", "http://localhost:3000,http://127.0.0.1:3000"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _allowed_origins],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# --- Auth ---------------------------------------------------------------------------


def get_current_user(authorization: str | None = Header(None)):
    """Resolve the Supabase JWT in the Authorization header to a user."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    try:
        user = supabase.auth.get_user(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}") from exc
    if not user or not user.user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user.user


# --- Small Supabase helpers -----------------------------------------------------------


async def db(query):
    """Run a (`supabase.table(...)...`) call off the event loop and return its result."""
    return await asyncio.to_thread(query.execute)


def fetch_profile_by(user_id: str) -> dict[str, Any]:
    """The user's profile row, or {} when it does not exist yet."""
    res = supabase.table("profiles").select("*").eq("id", user_id).maybe_single().execute()
    return res.data or {}


def fetch_effective_profile(user_id: str, language: str | None) -> dict[str, Any]:
    """Profile + the learner context for `language`, ready as agent `user_profile` deps.

    `target_language` is pinned to `language` (legacy rows without a stamp fall back to
    the profile's active language) so agents always speak of the session's language, not
    wherever the profile happens to point. The `user_languages` row's level/goals/
    interests overlay the profile fields when present.
    """
    profile = fetch_profile_by(user_id)
    effective_language = language or profile.get("target_language") or DEFAULT_LANGUAGE
    res = (
        supabase.table("user_languages")
        .select("level, goals, interests")
        .eq("user_id", user_id)
        .eq("language", effective_language)
        .maybe_single()
        .execute()
    )
    row = res.data or {}
    effective = {**profile, "target_language": effective_language}
    for field in ("level", "goals", "interests"):
        if row.get(field):
            effective[field] = row[field]
    return effective


def fetch_due_cards(user_id: str, language: str | None = None) -> list[dict[str, Any]]:
    """Cards due now (overdue or brand-new), optionally scoped to one language."""
    now = datetime.now(UTC).isoformat()
    query = supabase.table("cards").select("*").eq("user_id", user_id)
    if language:
        query = query.eq("language", language)
    res = query.or_(f"next_review.lte.{now},next_review.is.null").execute()
    return res.data or []


def compact_cards(rows: list[dict[str, Any]]) -> list[dict[str, str | None]]:
    """The only card fields the LLM ever sees; selection/grading happens by ID."""
    return [
        {"id": row.get("id"), "front": row.get("front") or "", "back": row.get("back") or ""}
        for row in rows
    ]


def fetch_recent_cards(
    user_id: str, language: str | None = None, limit: int = 300
) -> list[dict[str, Any]]:
    """The user's most recent cards for `language`, front/back only (read-only select)."""
    query = supabase.table("cards").select("front, back").eq("user_id", user_id)
    if language:
        query = query.eq("language", language)
    res = query.order("created_at", desc=True).limit(limit).execute()
    return res.data or []


def fetch_transcript(session_id: str, since: str | None = None) -> list[dict[str, Any]]:
    """A session's chat turns (plus payload-bearing event rows) oldest first.

    `since` (an ISO timestamp) keeps only rows at/after it. Chat turns stay
    `speaker`/`text`; system event rows keep their `payload` so restore can
    replay them.
    """
    res = (
        supabase.table("transcripts")
        .select("speaker, text, payload, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    rows = res.data or []
    if since is not None:
        rows = [row for row in rows if (row.get("created_at") or "") >= since]
    return rows


def fetch_current_panel(session_id: str) -> dict[str, Any] | None:
    """The panel currently on the learner's screen, from the transcript's panel
    events (last `panel_shown`, minus superseding `panel_hidden`).

    This is the same walk the UI performs over the persisted payloads; the
    backend replays it so the tutor's prompt can carry the panel content and
    stop re-showing panels that are already visible.
    """
    res = (
        supabase.table("transcripts")
        .select("payload")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    current: dict[str, Any] | None = None
    for row in res.data or []:
        payload = row.get("payload") or {}
        if not payload:
            continue
        kind = payload.get("kind")
        if kind == "panel_shown":
            panel = (payload.get("data") or {}).get("panel")
            if isinstance(panel, dict) and panel.get("markdown"):
                current = panel
        elif kind == "panel_hidden" and current is not None:
            hidden_id = payload.get("data", {}).get("panel_id") or ""
            if not hidden_id or hidden_id == current.get("id"):
                current = None
    return current


async def get_owned_session(session_id: str, user_id: str) -> dict[str, Any]:
    """A session row the user owns, raising 404 otherwise."""
    try:
        res = await asyncio.to_thread(
            lambda: (
                supabase.table("sessions")
                .select("*")
                .eq("id", session_id)
                .eq("user_id", user_id)
                .single()
                .execute()
            )
        )
    except APIError:
        raise HTTPException(status_code=404, detail="Session not found") from None
    if not res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    return res.data


def insert_transcript(
    session_id: str, speaker: str, text: str, payload: dict[str, Any] | None = None
) -> None:
    row: dict[str, Any] = {"session_id": session_id, "speaker": speaker, "text": text}
    if payload is not None:
        row["payload"] = payload
    supabase.table("transcripts").insert(row).execute()


def sse(event: dict[str, Any]) -> str:
    """Format one SSE frame; JSON-encoding keeps newlines inside payloads safe."""
    return f"data: {json.dumps(event)}\n\n"


# The analyst is prompted for 0-5 cards; this cap also holds if it over-produces.
MAX_NEW_CARDS = 5


def normalized_card_text(text: str) -> str:
    """Casefolded text without punctuation, for card-duplicate matching."""
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text.casefold())
    return " ".join(cleaned.split())


def harvest_new_cards(
    candidates: list[CardCandidate], existing_cards: list[dict[str, Any]]
) -> list[CardCandidate]:
    """Deterministic backstop for the analyst's card harvest — don't trust the prompt.

    Drops any candidate whose normalized front or back matches an existing card or an
    already-accepted candidate from this same session (repeated items yield one card),
    and caps the result at `MAX_NEW_CARDS`.
    """
    seen: set[str] = set()
    for row in existing_cards:
        for field in ("front", "back"):
            text = (row.get(field) or "").strip()
            if text:
                seen.add(normalized_card_text(text))
    kept: list[CardCandidate] = []
    for card in candidates:
        forms = [normalized_card_text(text) for text in (card.front, card.back) if text.strip()]
        if forms and seen.isdisjoint(forms):
            seen.update(forms)
            kept.append(card)
    return kept[:MAX_NEW_CARDS]


# --- FSRS ------------------------------------------------------------------------------


async def apply_fsrs_review(
    card_id: str,
    user_id: str,
    session_id: str,
    language: str | None,
    outcome: str,
    when: str | None = None,
) -> None:
    """Record one card review: update FSRS state and append a `card_reviews` row."""
    rating = VOCA_RATING_MAP.get(outcome)
    if rating is None:  # not_attempted or an unknown outcome label
        return
    res = await db(
        supabase.table("cards")
        .select("fsrs_data")
        .eq("id", card_id)
        .eq("user_id", user_id)
        .maybe_single()
    )
    if not res.data:
        return

    now = when or datetime.now(UTC).isoformat()
    current_state = res.data.get("fsrs_data") or new_card_state()
    new_state, review_log = review_card_state(current_state, rating)
    await db(
        supabase.table("cards")
        .update(
            {
                "fsrs_data": new_state,
                "next_review": next_review(new_state).isoformat(),
                "last_review": now,
            }
        )
        .eq("id", card_id)
    )
    # Append the graded review to the log so progress metrics (positive recalls,
    # review activity over time) exist; fsrs_data keeps no counts. `session_id`
    # lets recaps show this session's per-card results.
    await db(
        supabase.table("card_reviews").insert(
            {
                "card_id": card_id,
                "user_id": user_id,
                "session_id": session_id,
                "language": language,
                **review_log,
            }
        )
    )


# --- Models ---------------------------------------------------------------------------


class SessionResponse(BaseModel):
    session_id: str
    status: str
    created_at: str | None = None
    end_time: str | None = None
    recap: dict | None = None
    language: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int = 0


class ChatRequest(BaseModel):
    message: str
    session_id: str
    history: list[dict[str, Any]] | None = None


class SessionActionRequest(BaseModel):
    session_id: str


class TranslationRequest(BaseModel):
    text: str
    source_lang: str = "es"
    target_lang: str = "en"


class TranslationResponse(BaseModel):
    translation: str


translator_agent = Agent(
    model=voca_model,
    instructions="You are a professional translator. Return ONLY the translation, nothing else.",
)


def pydantic_history(
    history: list[dict[str, Any]] | None,
) -> list[ModelRequest | ModelResponse]:
    """Convert `[{role, content}]` pairs into pydantic-ai message history."""
    messages: list[ModelRequest | ModelResponse] = []
    for message in history or []:
        content = message.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        if message.get("role") == "assistant":
            messages.append(ModelResponse(parts=[TextPart(content=content)]))
        else:
            messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))
    return messages


# --- Tutor deps + SSE pump --------------------------------------------------------------


async def build_tutor_deps(
    user_id: str,
    session_id: str,
    language: str | None,
    profile: dict[str, Any],
    history: list[dict[str, Any]] | None,
) -> TutorDeps:
    """Everything the tutor agent needs for one streamed reply, plus its tool plumbing."""
    events: asyncio.Queue = asyncio.Queue()

    async def record_event(kind: str, data: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(
                insert_transcript, session_id, "system", "", {"kind": kind, "data": data}
            )
        except Exception:
            logger.exception("event persistence failed")

    due_cards: list[dict[str, Any]] = []
    try:
        due_cards = compact_cards(await asyncio.to_thread(fetch_due_cards, user_id, language))
    except Exception:
        logger.exception("due-card fetch failed")
    try:
        current_panel = await asyncio.to_thread(fetch_current_panel, session_id)
    except Exception:
        logger.exception("current-panel fetch failed")
        current_panel = None

    deps: TutorDeps = {
        "user_id": user_id,
        "session_id": session_id,
        "user_profile": profile,
        "due_cards": due_cards,
        "current_panel": current_panel,
        "events": events,
        "record_event": record_event,
    }
    return deps


async def tutor_frames(
    prompt: str,
    history: list[ModelRequest | ModelResponse],
    deps: TutorDeps,
    session_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """Stream one tutor reply as SSE-ready frames, interleaved with tool events.

    Text deltas and events produced by the tutor's tools share one queue, so the
    tool events arrive in order with the surrounding text. Tool calls that leak
    through streaming as raw text (`call:<tool>{...}`) are captured, hidden from
    the visible reply, and executed for real. The tutor's full text is persisted
    as a transcript row even when the stream fails mid-way.
    """
    full_response = ""
    queue = deps["events"]
    producer: asyncio.Task | None = None
    try:
        async with tutor_agent.run_stream(prompt, message_history=history, deps=deps) as result:

            async def emit(text: str) -> None:
                if not text:
                    return
                nonlocal full_response
                full_response += text
                await queue.put({"type": "delta", "text": text})

            async def consume():
                pending = ""
                try:
                    async for delta in result.stream_text(delta=True):
                        pending += delta
                        while True:
                            parsed = parse_tool_leak(pending)
                            if not parsed:
                                break
                            before, name, args, consumed = parsed
                            await emit(before)
                            pending = pending[consumed:]
                            logger.info("captured leaked tool call: %s (%s)", name, args)
                            await execute_leaked(name, args, deps)
                        # Hold back any tail that could still be a leak (gemma's
                        # panel calls stream long block arrays — never flush past
                        # the marker); only a long, markerless tail is prose.
                        flush = len(pending)
                        marker_idx = min(
                            (
                                idx
                                for tag in ("call:", "<tool_code>")
                                if (idx := pending.find(tag)) != -1
                            ),
                            default=-1,
                        )
                        if marker_idx == -1:
                            if flush > _LEAK_PASSTHROUGH_CAP:
                                await emit(pending)
                                pending = ""
                                flush = 0
                        else:
                            flush = marker_idx
                        flush = max(flush - _LEAK_HOLD, 0)
                        if flush:
                            await emit(pending[:flush])
                            pending = pending[flush:]
                    # Stream over: flush the rest (executing a complete call if
                    # its markup closed in the final delta).
                    while True:
                        parsed = parse_tool_leak(pending)
                        if not parsed:
                            break
                        before, name, args, consumed = parsed
                        await emit(before)
                        pending = pending[consumed:]
                        logger.info("captured leaked tool call: %s (%s)", name, args)
                        await execute_leaked(name, args, deps)
                    if pending.strip():
                        await emit(pending)
                finally:
                    await queue.put(None)

            producer = asyncio.ensure_future(consume())
            while (event := await queue.get()) is not None:
                yield event
            await producer
            producer = None
    except Exception:
        logger.exception("chat stream failed")
        yield {"type": "error", "message": "The tutor hit an unexpected error. Please try again."}
    finally:
        if producer is not None:
            producer.cancel()
        if full_response:
            await asyncio.to_thread(insert_transcript, session_id, "tutor", full_response)


def sse_stream(frames: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    async def stream():
        async for frame in frames:
            yield sse(frame)
        yield sse({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


# --- Routes ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ollama/health")
async def ollama_health():
    """Report whether the local Ollama OpenAI-compatible server is reachable."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{LLM_BASE_URL.rstrip('/')}/models", timeout=2.0)
            return {"status": "ok", "ollama_reachable": response.status_code < 500}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@app.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    user=Depends(get_current_user), language: str | None = None, limit: int = 50, offset: int = 0
):
    """Paged session list, newest first; `total` is the full count behind the page."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    query = supabase.table("sessions").select("*", count="exact").eq("user_id", user.id)
    if language:
        query = query.eq("language", language)
    res = await db(query.order("created_at", desc=True).range(offset, offset + limit - 1))
    return SessionListResponse(
        total=res.count or 0,
        sessions=[
            SessionResponse(
                session_id=session["id"],
                status=session["status"],
                created_at=session.get("created_at"),
                end_time=session.get("end_time"),
                recap=session.get("recap"),
                language=session.get("language"),
            )
            for session in (res.data or [])
        ],
    )


@app.post("/sessions/start", response_model=SessionResponse)
async def start_session(user=Depends(get_current_user)):
    profile = await asyncio.to_thread(fetch_profile_by, user.id)
    language = (profile or {}).get("target_language") or DEFAULT_LANGUAGE
    res = await db(
        supabase.table("sessions").insert(
            {"user_id": user.id, "status": "active", "language": language}
        )
    )
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create session")
    session = res.data[0]
    now = datetime.now(UTC).isoformat()
    # Practice stamps "latest practiced" in two places: the user_languages row
    # (drives the practiced-languages dropdown ordering) and the profile pointer
    # (what the user lands on for their next login).
    await db(
        supabase.table("user_languages").upsert(
            {"user_id": user.id, "language": language, "last_practiced_at": now}
        )
    )
    await db(supabase.table("profiles").update({"target_language": language}).eq("id", user.id))
    return SessionResponse(
        session_id=session["id"], status=session["status"], language=session.get("language")
    )


@app.post("/sessions/end")
async def end_session(request: SessionActionRequest, user=Depends(get_current_user)):
    """Mark the session completed and run the post-session analyst."""
    session = await get_owned_session(request.session_id, user.id)
    if session["status"] != "active":
        raise HTTPException(status_code=409, detail="Session has already ended")
    now = datetime.now(UTC).isoformat()

    transcript = await db(
        supabase.table("transcripts")
        .select("speaker, text, payload")
        .eq("session_id", session["id"])
        .order("created_at")
    )
    language = session.get("language")
    # The analyst sees every due card: its FSRS rubric maps the whole transcript
    # (whatever the conversation touched — panel exercises, review weaving,
    # casual usage) to card statuses.
    due_rows = await asyncio.to_thread(fetch_due_cards, user.id, language)
    due_cards = compact_cards(due_rows)
    existing_cards = await asyncio.to_thread(fetch_recent_cards, user.id, language)

    result = await post_session_agent.run(
        "Analyze the session and generate cards and recap.",
        deps={
            "user_id": user.id,
            "session_id": session["id"],
            "transcript": transcript.data or [],
            "due_cards": due_cards,
            "existing_cards": existing_cards,
            "target_language": language,
        },
    )
    analysis = result.output
    # Backstop: drop duplicates of existing/accepted cards and anything past the cap
    # before either writing rows or putting cards in the recap.
    new_cards = harvest_new_cards(analysis.new_cards, existing_cards)

    await db(
        supabase.table("sessions")
        .update({"status": "completed", "end_time": now})
        .eq("id", session["id"])
    )

    if new_cards:
        await db(
            supabase.table("cards").insert(
                [
                    {
                        "user_id": user.id,
                        "type": card.type,
                        "front": card.front,
                        "back": card.back,
                        "source_sentence": card.source_sentence,
                        # The card belongs to the session's language.
                        "language": language,
                        "fsrs_data": new_card_state(),
                        "next_review": now,  # new cards are due immediately
                    }
                    for card in new_cards
                ]
            )
        )

    for review in analysis.reviewed_cards:
        await apply_fsrs_review(review.card_id, user.id, session["id"], language, review.outcome)

    profile_updates = analysis.profile_updates.model_dump(exclude_none=True)
    if profile_updates:
        # Per-language details (level/goals/interests) live in user_languages.
        await db(
            supabase.table("user_languages").upsert(
                {"user_id": user.id, "language": language, **profile_updates}
            )
        )

    recap = analysis.recap.model_dump()
    # Words the learner actually produced this session — real data, unlike the
    # agent-invented "time spoken" (removed from the recap model).
    recap["user_word_count"] = sum(
        len((message.get("text") or "").split())
        for message in (transcript.data or [])
        if message.get("speaker") == "user"
    )
    # Always present so the recap page can render review material without
    # re-querying the cards table (empty when nothing was created).
    recap["new_cards"] = [{"type": c.type, "front": c.front, "back": c.back} for c in new_cards]
    # The review scorecard: FSRS rating per reviewed word (rating is null for
    # `not_attempted` — no review was logged). The recap page renders these as
    # bare icons with the rating on hover; no schedules, no explanations.
    due_by_id = {row.get("id"): row for row in due_rows}
    recap["reviewed_cards"] = []
    for review in analysis.reviewed_cards:
        card_row = due_by_id.get(review.card_id)
        if card_row is None:
            continue  # never showcase a grade outside the due-card slate
        rating = VOCA_RATING_MAP.get(review.outcome)
        entry = {
            "front": card_row.get("front") or "",
            "back": card_row.get("back") or "",
            "rating": int(rating) if rating is not None else None,
        }
        if not any(item["front"] == entry["front"] for item in recap["reviewed_cards"]):
            recap["reviewed_cards"].append(entry)
    await db(supabase.table("sessions").update({"recap": recap}).eq("id", session["id"]))

    return {
        "status": "session ended",
        "recap": recap,
        "new_cards_count": len(new_cards),
    }


@app.post("/translate", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest):
    prompt = (
        f"Translate the following text from {request.source_lang} to "
        f"{request.target_lang}:\n{request.text}"
    )
    result = await translator_agent.run(prompt)
    return TranslationResponse(translation=result.output)


@app.post("/chat")
async def chat(request: ChatRequest, user=Depends(get_current_user)):
    session = await get_owned_session(request.session_id, user.id)
    if session["status"] != "active":
        raise HTTPException(status_code=409, detail="Session has already ended")
    language = session.get("language")
    profile = await asyncio.to_thread(fetch_effective_profile, user.id, language)

    # Record the user's turn before responding so a mid-stream failure cannot lose it.
    await asyncio.to_thread(insert_transcript, session["id"], "user", request.message)

    deps = await build_tutor_deps(user.id, session["id"], language, profile, request.history)

    async def frames():
        async for frame in tutor_frames(
            request.message, pydantic_history(request.history), deps, session["id"]
        ):
            yield frame

    return sse_stream(frames())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("voca.main:app", host="0.0.0.0", port=8000)
