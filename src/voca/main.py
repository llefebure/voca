"""Voca FastAPI backend.

Chat is streamed as Server-Sent Events with single-line JSON frames:
`data: {"type":"delta","text":...}` for chat text, `{"type":"status","text":...}`
for transient chips, `{"type":"event","kind":...,"data":...}` for structured UI
events (proposal cards, lesson material, summaries), and `{"type":"done"}` (or
`{"type":"error"}`), so newlines inside payloads cannot corrupt the stream. The
session's conversation phase (small talk ⇄ lessons) is derived from
`sessions.lessons` in `services/lesson_flow`. Serve this app with
`uv run uvicorn voca.main:app` from the repository root.
"""

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Callable
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

from voca.agents.lesson_grader_agent import GraderDeps, lesson_grader_agent
from voca.agents.post_session_agent import CardCandidate, post_session_agent
from voca.agents.session_planner_agent import PlannerDeps, session_planner_agent
from voca.agents.tutor_agent import TutorDeps, tutor_agent
from voca.services import lesson_flow
from voca.services.languages import DEFAULT_LANGUAGE
from voca.services.lesson_templates import find_template, template_name
from voca.services.llm import LLM_BASE_URL, voca_model
from voca.services.srs import (
    VOCA_RATING_MAP,
    new_card_state,
    next_review,
    review_card_state,
)
from voca.services.supabase_client import supabase

load_dotenv()

app = FastAPI(title="Voca Backend")

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

    `since` (an ISO timestamp) keeps only rows at/after it — the slice the lesson
    grader sees. Chat turns stay `speaker`/`text`; system event rows keep their
    `payload` so restore can replay them.
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


def session_lessons(session: dict[str, Any]) -> list[dict[str, Any]]:
    """The session's lesson instances as stored in `sessions.lessons`."""
    return session.get("lessons") or []


async def persist_lessons(session_id: str, lessons: list[dict[str, Any]]) -> None:
    await db(supabase.table("sessions").update({"lessons": lessons}).eq("id", session_id))


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
    lesson_id: str | None = None,
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
    # lets recaps show this session's per-card results; `lesson_id` marks grades
    # the per-lesson grader produced.
    await db(
        supabase.table("card_reviews").insert(
            {
                "card_id": card_id,
                "user_id": user_id,
                "session_id": session_id,
                "language": language,
                "lesson_id": lesson_id,
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


class LessonActionRequest(SessionActionRequest):
    reason: str | None = None


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


# --- Lesson flow: proposal / activation / grading --------------------------------------


def required_missing_blocks(template_id: str, present_types: list[str]) -> list[str]:
    """Required block types of `template_id` that are not in `present_types`."""
    template = find_template(template_id)
    if template is None:
        return []
    return [block for block in template["required_blocks"] if block not in present_types]


async def run_proposal(user_id: str, session_id: str, language: str, idea: str = "") -> dict | None:
    """Design a lesson proposal grounded in this session's recent chat, persist it.

    Returns the new lesson instance (the newest entry of `sessions.lessons`), or
    None when the planner could not produce template-valid material.
    """
    profile = await asyncio.to_thread(fetch_effective_profile, user_id, language)
    due_rows = await asyncio.to_thread(fetch_due_cards, user_id, language)
    due_cards = compact_cards(due_rows)
    transcript = await asyncio.to_thread(fetch_transcript, session_id)
    recent_turns = [
        {"speaker": row["speaker"], "text": row["text"]}
        for row in transcript
        if row.get("speaker") in ("user", "tutor") and (row.get("text") or "").strip()
    ][-12:]
    session_row = await get_owned_session(session_id, user_id)
    stored_lessons = session_lessons(session_row)

    deps: PlannerDeps = {
        "user_id": user_id,
        "user_profile": profile,
        "due_cards": due_cards,
        "recent_transcript": recent_turns,
        "session_lessons": [
            {"status": lesson.get("status"), "title": (lesson.get("spec") or {}).get("title")}
            for lesson in stored_lessons
        ],
        **({"idea": idea} if idea else {}),
    }

    feedback = "Design this lesson proposal."
    by_id = {card["id"]: card for card in due_cards}
    for _attempt in range(2):
        try:
            result = await session_planner_agent.run(feedback, deps=deps)
            proposal = result.output
        except Exception:
            logger.exception("lesson planner run failed")
            return None
        blocks, dropped = lesson_flow.validate_material(
            proposal.lesson.template, [b.model_dump() for b in proposal.material]
        )
        missing = required_missing_blocks(proposal.lesson.template, [b.type for b in blocks])
        target_cards = [by_id[cid] for cid in proposal.target_card_ids or [] if cid in by_id]
        if not missing and blocks:
            lesson = lesson_flow.new_lesson(
                proposal.lesson,
                [b.model_dump() for b in blocks],
                compact_cards(target_cards),
                proposal.reason,
                proposal.intro_line,
            )
            if dropped:
                logger.info(
                    "planner produced %s disallowed block(s) for %s: %s",
                    len(dropped),
                    proposal.lesson.template,
                    dropped,
                )
            stored_lessons.append(lesson)
            await persist_lessons(session_id, stored_lessons)
            return lesson
        feedback = (
            "Your previous proposal's material was invalid for this template. "
            f"Missing required blocks: {missing or '(none)'}; include every required block "
            "and only blocks the template allows."
        )
    logger.warning("planner could not produce valid material for template")
    return None


async def activate_proposal(user_id: str, session_id: str) -> dict | None:
    """Activate the session's pending proposal in the DB; return the lesson."""
    session_row = await get_owned_session(session_id, user_id)
    lessons = session_lessons(session_row)
    pending = lesson_flow.pending_proposal(lessons)
    if pending is None or lesson_flow.active_lesson(lessons):
        return None
    lesson = lesson_flow.activate(pending)
    await persist_lessons(session_id, lesson_flow.update_lessons(lessons, lesson["id"], lesson))
    return lesson


async def grade_and_complete(user_id: str, session_id: str, language: str | None) -> dict | None:
    """Grade the active lesson and persist its completion; return the lesson row."""
    session_row = await get_owned_session(session_id, user_id)
    lessons = session_lessons(session_row)
    lesson = lesson_flow.active_lesson(lessons)
    if lesson is None:
        return None

    transcript = await asyncio.to_thread(fetch_transcript, session_id, lesson.get("accepted_at"))
    try:
        result = await lesson_grader_agent.run(
            "Grade this lesson.",
            deps=GraderDeps(language=language, lesson=lesson, transcript=transcript),
        )
        grades = result.output
    except Exception:
        logger.exception("lesson grader run failed")
        return None

    graded = [
        {
            "card_id": grade.card_id,
            "outcome": grade.outcome,
            "bonus_use": grade.bonus_use,
            "evidence": grade.evidence,
        }
        for grade in grades.grades
    ]
    for grade in graded:
        if grade["card_id"] not in {c["id"] for c in lesson.get("target_cards", [])}:
            continue  # never grade a card the lesson did not target
        await apply_fsrs_review(
            grade["card_id"], user_id, session_id, language, grade["outcome"], lesson["id"]
        )

    summary = {**grades.summary.model_dump(), "bonus_uses": grades.bonus_uses}
    completed = lesson_flow.complete(lesson, graded, summary)
    await persist_lessons(session_id, lesson_flow.update_lessons(lessons, lesson["id"], completed))
    return completed


# --- Tutor deps + SSE pump --------------------------------------------------------------


async def build_tutor_deps(
    user_id: str,
    session_id: str,
    language: str | None,
    lessons: list[dict[str, Any]],
    profile: dict[str, Any],
    history: list[dict[str, Any]] | None,
) -> TutorDeps:
    """Everything the tutor agent needs for one streamed reply, plus its tool plumbing."""
    phase = lesson_flow.derive_phase(lessons)
    events: asyncio.Queue = asyncio.Queue()

    async def run_planner(idea: str = "") -> dict | None:
        try:
            return await run_proposal(user_id, session_id, language or DEFAULT_LANGUAGE, idea)
        except Exception:
            logger.exception("proposal creation failed")
            return None

    async def activate() -> dict | None:
        try:
            lesson = await activate_proposal(user_id, session_id)
            if lesson is None:
                return None
            await asyncio.to_thread(
                insert_transcript,
                session_id,
                "system",
                "",
                {"kind": "lesson_started", "data": {"lesson": lesson}},
            )
            return lesson
        except Exception:
            logger.exception("lesson activation failed")
            return None

    async def complete() -> dict | None:
        try:
            lesson = await grade_and_complete(user_id, session_id, language)
            if lesson is None:
                return None
            await asyncio.to_thread(
                insert_transcript,
                session_id,
                "system",
                "",
                {"kind": "lesson_completed", "data": {"lesson": lesson}},
            )
            return lesson
        except Exception:
            logger.exception("lesson completion failed")
            return None

    async def record_event(kind: str, data: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(
                insert_transcript, session_id, "system", "", {"kind": kind, "data": data}
            )
        except Exception:
            logger.exception("event persistence failed")

    callbacks: dict[str, Callable]
    callbacks = {
        "run_planner": run_planner,
        "activate_proposal": activate,
        "grade_and_complete": complete,
        "record_event": record_event,
    }

    smalltalk_turns = sum(1 for message in history or [] if message.get("role") == "user")
    due_cards = []
    if phase != lesson_flow.PHASE_LESSON:
        try:
            due_cards = compact_cards(await asyncio.to_thread(fetch_due_cards, user_id, language))
        except Exception:
            logger.exception("due-card fetch failed")

    deps: TutorDeps = {
        "user_id": user_id,
        "session_id": session_id,
        "user_profile": profile,
        "phase": phase,
        "active_lesson": lesson_flow.active_lesson(lessons),
        "pending_proposal": lesson_flow.pending_proposal(lessons),
        "session_lessons": lessons,
        "due_cards": due_cards,
        "smalltalk_turns": smalltalk_turns,
        "events": events,
        **callbacks,  # type: ignore[arg-type]
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
    tool events arrive in order with the surrounding text. The tutor's full text
    is persisted as a transcript row even when the stream fails mid-way.
    """
    full_response = ""
    queue = deps["events"]
    producer: asyncio.Task | None = None
    try:
        async with tutor_agent.run_stream(prompt, message_history=history, deps=deps) as result:

            async def consume():
                nonlocal full_response
                try:
                    async for delta in result.stream_text(delta=True):
                        full_response += delta
                        await queue.put({"type": "delta", "text": delta})
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


@app.post("/sessions/lessons/accept")
async def accept_lesson(request: SessionActionRequest, user=Depends(get_current_user)):
    """Activate the pending lesson proposal and stream the tutor's lesson opener."""
    session = await get_owned_session(request.session_id, user.id)
    if session["status"] != "active":
        raise HTTPException(status_code=409, detail="Session has already ended")
    lessons = session_lessons(session)
    if lesson_flow.derive_phase(lessons) != lesson_flow.PHASE_AWAITING_ACCEPT:
        raise HTTPException(status_code=409, detail="No lesson proposal is waiting")

    lesson = lesson_flow.activate(lesson_flow.pending_proposal(lessons))
    stored = lesson_flow.update_lessons(lessons, lesson["id"], lesson)
    await persist_lessons(session["id"], stored)
    await asyncio.to_thread(
        insert_transcript,
        session["id"],
        "system",
        "",
        {"kind": "lesson_started", "data": {"lesson": lesson}},
    )

    profile = await asyncio.to_thread(fetch_effective_profile, user.id, session.get("language"))
    deps = await build_tutor_deps(
        user.id, session["id"], session.get("language"), stored, profile, []
    )

    async def frames():
        # The material + opener: the lesson event first, then the streamed reply.
        yield {"type": "event", "kind": "lesson_started", "data": {"lesson": lesson}}
        async for frame in tutor_frames(
            "Open the lesson now with its opening line, then start the first step.",
            [],
            deps,
            session["id"],
        ):
            yield frame

    return sse_stream(frames())


@app.post("/sessions/lessons/decline")
async def decline_lesson(request: LessonActionRequest, user=Depends(get_current_user)):
    """Mark the pending lesson proposal declined so the tutor stops referring to it."""
    session = await get_owned_session(request.session_id, user.id)
    if session["status"] != "active":
        raise HTTPException(status_code=409, detail="Session has already ended")
    lessons = session_lessons(session)
    pending = lesson_flow.pending_proposal(lessons)
    if pending is None:
        raise HTTPException(status_code=409, detail="No lesson proposal is waiting")

    declined = lesson_flow.decline(pending, request.reason)
    await persist_lessons(
        session["id"], lesson_flow.update_lessons(lessons, declined["id"], declined)
    )
    await asyncio.to_thread(
        insert_transcript,
        session["id"],
        "system",
        "",
        {
            "kind": "lesson_declined",
            "data": {
                "lesson_id": declined["id"],
                "title": (declined.get("spec") or {}).get("title"),
                "reason": request.reason,
            },
        },
    )
    return {"status": "declined", "lesson_id": declined["id"]}


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
    lessons = session_lessons(session)
    # Cards any lesson already graded are excluded — the analyst sweeps the rest
    # (small-talk usage), so nothing is double-graded.
    graded_ids = {grade["card_id"] for lesson in lessons for grade in lesson.get("grades") or []}
    due_rows = await asyncio.to_thread(fetch_due_cards, user.id, language)
    due_cards = compact_cards([row for row in due_rows if row.get("id") not in graded_ids])
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
            "lessons": lessons,
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
    # The lessons this session ran (and their per-lesson outcomes), always in
    # recap order; the recap page renders these instead of the retired plan.
    recap["lessons"] = [
        {
            "id": lesson["id"],
            "status": lesson.get("status"),
            "title": (lesson.get("spec") or {}).get("title"),
            "template": (lesson.get("spec") or {}).get("template"),
            "template_name": template_name((lesson.get("spec") or {}).get("template")),
            "summary": lesson.get("summary"),
            "bonus_uses_count": len(lesson.get("summary", {}).get("bonus_uses") or []),
        }
        for lesson in lessons
    ]
    # Always present so the recap page can render review material without
    # re-querying the cards table (empty when nothing was created).
    recap["new_cards"] = [{"type": c.type, "front": c.front, "back": c.back} for c in new_cards]
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

    deps = await build_tutor_deps(
        user.id, session["id"], language, session_lessons(session), profile, request.history
    )

    return sse_stream(
        tutor_frames(request.message, pydantic_history(request.history), deps, session["id"])
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("voca.main:app", host="0.0.0.0", port=8000)
