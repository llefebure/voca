"""Voca FastAPI backend.

Chat is streamed as Server-Sent Events with single-line JSON frames:
`data: {"type":"delta","text":...}` until `{"type":"done"}` (or `{"type":"error"}`), so
newlines inside deltas cannot corrupt the stream. Serve this app with
`uv run uvicorn voca.main:app` from the repository root.
"""

import asyncio
import json
import os
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

from voca.agents.post_session_agent import post_session_agent
from voca.agents.session_planner_agent import session_planner_agent
from voca.agents.tutor_agent import TutorDeps, spanish_tutor
from voca.services.llm import LLM_BASE_URL, ollama_model
from voca.services.srs import (
    VOCA_RATING_MAP,
    new_card_state,
    next_review,
    update_card_state,
)
from voca.services.supabase_client import supabase

load_dotenv()

app = FastAPI(title="Voca Backend")

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


async def get_current_user(authorization: str | None = Header(None)):
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


def fetch_due_cards(user_id: str) -> list[dict[str, Any]]:
    """Cards that should be reviewed now: overdue, or brand-new (never scheduled)."""
    now = datetime.now(UTC).isoformat()
    res = (
        supabase.table("cards")
        .select("*")
        .eq("user_id", user_id)
        .or_(f"next_review.lte.{now},next_review.is.null")
        .execute()
    )
    return res.data or {}


def get_owned_session(session_id: str, user_id: str) -> dict[str, Any]:
    """A session row the user owns, raising 404 otherwise."""
    try:
        res = (
            supabase.table("sessions")
            .select("*")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .single()
            .execute()
        )
    except APIError:
        raise HTTPException(status_code=404, detail="Session not found") from None
    if not res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    return res.data


def insert_transcript(session_id: str, speaker: str, text: str) -> None:
    supabase.table("transcripts").insert(
        {"session_id": session_id, "speaker": speaker, "text": text}
    ).execute()


def sse(event: dict[str, Any]) -> str:
    """Format one SSE frame; JSON-encoding keeps newlines inside deltas safe."""
    return f"data: {json.dumps(event)}\n\n"


# --- Models ---------------------------------------------------------------------------


class SessionResponse(BaseModel):
    session_id: str
    status: str
    created_at: str | None = None
    end_time: str | None = None
    recap: dict | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]


class ChatRequest(BaseModel):
    message: str
    session_id: str
    history: list[dict[str, Any]] | None = None


class TranslationRequest(BaseModel):
    text: str
    source_lang: str = "es"
    target_lang: str = "en"


class TranslationResponse(BaseModel):
    translation: str


translator_agent = Agent(
    model=ollama_model,
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
async def list_sessions(user=Depends(get_current_user)):
    res = await db(
        supabase.table("sessions").select("*").eq("user_id", user.id).order("created_at", desc=True)
    )
    return SessionListResponse(
        sessions=[
            SessionResponse(
                session_id=session["id"],
                status=session["status"],
                created_at=session.get("created_at"),
                end_time=session.get("end_time"),
                recap=session.get("recap"),
            )
            for session in (res.data or [])
        ]
    )


@app.post("/sessions/start", response_model=SessionResponse)
async def start_session(user=Depends(get_current_user)):
    res = await db(supabase.table("sessions").insert({"user_id": user.id, "status": "active"}))
    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create session")
    session = res.data[0]
    return SessionResponse(session_id=session["id"], status=session["status"])


@app.post("/sessions/plan")
async def plan_session(session_id: str, user=Depends(get_current_user)):
    session = get_owned_session(session_id, user.id)

    profile, due_cards, lessons = await asyncio.gather(
        asyncio.to_thread(fetch_profile_by, user.id),
        asyncio.to_thread(fetch_due_cards, user.id),
        db(supabase.table("lessons").select("*")),
    )
    profile = profile or {}

    result = await session_planner_agent.run(
        "Plan the session.",
        deps={
            "user_id": user.id,
            "user_profile": profile,
            "due_cards": due_cards,
            "available_lessons": lessons.data or [],
        },
    )
    plan = result.output

    await db(supabase.table("sessions").update({"plan": plan.model_dump()}).eq("id", session["id"]))
    return plan


@app.post("/sessions/end")
async def end_session(session_id: str, user=Depends(get_current_user)):
    """Mark the session completed and run the post-session analyst."""
    session = get_owned_session(session_id, user.id)
    now = datetime.now(UTC).isoformat()

    transcript = await db(
        supabase.table("transcripts")
        .select("speaker, text")
        .eq("session_id", session["id"])
        .order("created_at")
    )
    due_cards = await asyncio.to_thread(fetch_due_cards, user.id)

    result = await post_session_agent.run(
        "Analyze the session and generate cards and recap.",
        deps={
            "user_id": user.id,
            "session_id": session["id"],
            "transcript": transcript.data or [],
            "due_cards": due_cards,
        },
    )
    analysis = result.output

    await db(
        supabase.table("sessions")
        .update({"status": "completed", "end_time": now})
        .eq("id", session["id"])
    )

    if analysis.new_cards:
        await db(
            supabase.table("cards").insert(
                [
                    {
                        "user_id": user.id,
                        "type": card.type,
                        "front": card.front,
                        "back": card.back,
                        "source_sentence": card.source_sentence,
                        # `state` is a plain label; the FSRS schedule lives in `fsrs_data`.
                        "state": "new",
                        "fsrs_data": new_card_state(),
                        "next_review": now,  # new cards are due immediately
                    }
                    for card in analysis.new_cards
                ]
            )
        )

    for review in analysis.reviewed_cards:
        rating = VOCA_RATING_MAP.get(review.outcome)
        if rating is None:  # not_attempted or an unknown outcome label
            continue

        res = await db(
            supabase.table("cards")
            .select("fsrs_data")
            .eq("id", review.card_id)
            .eq("user_id", user.id)
            .maybe_single()
        )
        if not res.data:
            continue

        current_state = res.data.get("fsrs_data") or new_card_state()
        new_state = update_card_state(current_state, rating)
        await db(
            supabase.table("cards")
            .update(
                {
                    "fsrs_data": new_state,
                    "next_review": next_review(new_state).isoformat(),
                    "last_review": now,
                }
            )
            .eq("id", review.card_id)
        )

    if analysis.profile_updates:
        await db(supabase.table("profiles").update(analysis.profile_updates).eq("id", user.id))

    if analysis.recap:
        await db(
            supabase.table("sessions")
            .update({"recap": analysis.recap.model_dump()})
            .eq("id", session["id"])
        )

    return {
        "status": "session ended",
        "recap": analysis.recap,
        "new_cards_count": len(analysis.new_cards),
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
    session = get_owned_session(request.session_id, user.id)
    profile = await asyncio.to_thread(fetch_profile_by, user.id)

    # Record the user's turn before responding so a mid-stream failure cannot lose it.
    await asyncio.to_thread(insert_transcript, session["id"], "user", request.message)

    deps: TutorDeps = {
        "user_id": user.id,
        "user_profile": profile,
        "session_id": session["id"],
    }
    history = pydantic_history(request.history)

    async def event_generator():
        full_response = ""
        try:
            async with spanish_tutor.run_stream(
                request.message, message_history=history, deps=deps
            ) as result:
                async for delta in result.stream_text(delta=True):
                    full_response += delta
                    yield sse({"type": "delta", "text": delta})
        except Exception as exc:
            yield sse({"type": "error", "message": str(exc)})
        finally:
            # Save whatever the tutor produced, even if the stream failed mid-way.
            if full_response:
                await asyncio.to_thread(insert_transcript, session["id"], "tutor", full_response)
        yield sse({"type": "done"})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("voca.main:app", host="0.0.0.0", port=8000)
