from datetime import UTC, datetime

from agents.post_session_agent import post_session_agent
from agents.session_planner_agent import session_planner_agent
from agents.tutor_agent import ollama_model, spanish_tutor
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart
from services.srs import VOCA_RATING_MAP, srs_service
from services.supabase_client import supabase

load_dotenv()

app = FastAPI(title="Voca Backend")

# Enable CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_current_user(authorization: str | None = Header(None)):
    print(f"DEBUG: get_current_user called with auth: {authorization is not None}")
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")

    try:
        # Expecting "Bearer <token>"
        token = authorization.split(" ")[1]
        print("DEBUG: Verifying token with Supabase...")
        # Verify the user with Supabase
        user = supabase.auth.get_user(token)
        print(f"DEBUG: Supabase user verified: {user.user.id if user and user.user else 'Failed'}")
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user.user
    except Exception as e:
        print(f"DEBUG: Authentication failed: {e!s}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {e!s}")

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
    history: list | None = None

class ChatResponse(BaseModel):
    response: str
    history: list

class TranslationRequest(BaseModel):
    text: str
    source_lang: str = "es"
    target_lang: str = "en"

class TranslationResponse(BaseModel):
    translation: str

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/ollama/health")
async def ollama_health():
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"), timeout=2.0)
            return {"status": "ok", "ollama_reachable": response.status_code == 200}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/sessions", response_model=SessionListResponse)
async def list_sessions(user=Depends(get_current_user)):
    print(f"DEBUG: list_sessions called for user {user.id}")
    res = supabase.table("sessions") \
        .select("*") \
        .eq("user_id", user.id) \
        .order("created_at", desc=True) \
        .execute()
    print(f"DEBUG: Supabase query returned {len(res.data or [])} sessions")

    sessions = []
    for s in (res.data or []):
        sessions.append(SessionResponse(
            session_id=s["id"],
            status=s["status"],
            created_at=s.get("created_at"),
            end_time=s.get("end_time"),
            recap=s.get("recap")
        ))
    
    return SessionListResponse(sessions=sessions)

@app.post("/sessions/start", response_model=SessionResponse)
async def start_session(user=Depends(get_current_user)):
    res = supabase.table("sessions").insert({
        "user_id": user.id,
        "status": "active"
    }).execute()

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create session")

    session = res.data[0]
    return SessionResponse(session_id=session["id"], status=session["status"])

@app.post("/sessions/plan")
async def plan_session(session_id: str, user=Depends(get_current_user)):
    # Fetch data for planning
    profile_res = supabase.table("profiles").select("*").eq("id", user.id).single().execute()
    profile = profile_res.data or {}

    due_cards_res = supabase.table("cards").select("*").lt("next_review", datetime.now(UTC).isoformat()).eq("user_id", user.id).execute()
    lessons_res = supabase.table("lessons").select("*").execute()

    deps = {
        "user_id": user.id,
        "user_profile": profile,
        "due_cards": due_cards_res.data or [],
        "available_lessons": lessons_res.data or []
    }
    result = await session_planner_agent.run("Plan the session.", deps=deps)
    plan = result.output

    # Store the plan in the session
    supabase.table("sessions").update({
        "plan": plan.model_dump()
    }).eq("id", session_id).execute()

    return plan

@app.post("/sessions/end")
async def end_session(session_id: str, user=Depends(get_current_user)):
    # Verify session belongs to user
    session_check = supabase.table("sessions").select("*").eq("id", session_id).eq("user_id", user.id).single().execute()
    if not session_check.data:
        raise HTTPException(status_code=404, detail="Session not found")

    now = datetime.now(UTC).isoformat()
    supabase.table("sessions").update({
        "status": "completed",
        "end_time": now
    }).eq("id", session_id).execute()

    # Trigger Post-Session Analysis
    transcript_res = supabase.table("transcripts").select("*").eq("session_id", session_id).order("created_at").execute()
    due_cards_res = supabase.table("cards").select("*").eq("user_id", user.id).eq("state", "new").execute() # Simplified for now

    deps = {
        "user_id": user.id,
        "session_id": session_id,
        "transcript": transcript_res.data or [],
        "due_cards": due_cards_res.data or []
    }

    result = await post_session_agent.run("Analyze the session and generate cards and recap.", deps=deps)
    analysis = result.output

    # Save new cards to DB
    if analysis.new_cards:
        cards_to_insert = [
            {
                "user_id": user.id,
                "type": card.type,
                "front": card.front,
                "back": card.back,
                "source_sentence": card.source_sentence,
                "state": srs_service.create_new_card_state()
            }
            for card in analysis.new_cards
        ]
        supabase.table("cards").insert(cards_to_insert).execute()

    # Update reviewed cards using SRS
    if analysis.reviewed_cards:
        for review in analysis.reviewed_cards:
            outcome = review.outcome
            if outcome == "not_attempted":
                continue

            rating = VOCA_RATING_MAP.get(outcome)
            if not rating:
                continue

            # Get current card state
            card_res = supabase.table("cards").select("fsrs_data").eq("id", review.card_id).single().execute()
            if not card_res.data:
                continue

            current_state = card_res.data.get("fsrs_data", "{}")
            new_state = srs_service.update_card_state(current_state, rating)
            next_review = srs_service.get_next_review(new_state)

            supabase.table("cards").update({
                "fsrs_data": new_state,
                "next_review": next_review.isoformat(),
                "last_review": datetime.now(UTC).isoformat()
            }).eq("id", review.card_id).execute()

    # Update profile
    if analysis.profile_updates:
        supabase.table("profiles").update(analysis.profile_updates).eq("id", user.id).execute()

    # Save recap to session
    supabase.table("sessions").update({
        "recap": analysis.recap.model_dump()
    }).eq("id", session_id).execute()

    return {
        "status": "session ended",
        "recap": analysis.recap,
        "new_cards_count": len(analysis.new_cards)
    }

@app.post("/translate", response_model=TranslationResponse)
async def translate_text(request: TranslationRequest):
    # Use a simple Pydantic AI agent for translation
    translator = Agent(
        model=ollama_model,
        instructions=f"You are a professional translator. Translate the text from {request.source_lang} to {request.target_lang}. Return ONLY the translation."
    )
    result = await translator.run(request.text)
    # Result is a string because no result_type is defined
    return TranslationResponse(translation=result.output)

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user=Depends(get_current_user)):
    # Fetch session data for current phase
    session_res = supabase.table("sessions").select("current_phase").eq("id", request.session_id).single().execute()
    if not session_res.data:
        raise HTTPException(status_code=404, detail="Session not found")

    current_phase = session_res.data.get("current_phase", "opener")

    # Fetch user profile for agent dependencies
    profile_res = supabase.table("profiles").select("*").eq("id", user.id).single().execute()
    profile = profile_res.data or {}

    deps = {
        "user_id": user.id,
        "user_profile": profile,
        "session_id": request.session_id,
        "current_phase": current_phase
    }

    # Save user message to transcript
    supabase.table("transcripts").insert({
        "session_id": request.session_id,
        "speaker": "user",
        "text": request.message
    }).execute()

    # Use run with deps
    history = []
    for m in (request.history or []):
        if isinstance(m, dict):
            role = m.get("role")
            content = m.get("content", "")
            if role == "user":
                history.append(ModelRequest(parts=[TextPart(content)]))
            elif role == "assistant":
                history.append(ModelResponse(parts=[TextPart(content)]))
            else:
                # Fallback for other roles or formats
                history.append(ModelRequest(parts=[TextPart(content)]))
        else:
            history.append(m)

    result = await spanish_tutor.run(
        request.message,
        message_history=history,
        deps=deps
    )

    # Use .output for the response (TutorResponse model)
    response_data = result.output

    # Update session phase if the agent signaled a transition
    if response_data.next_phase:
        supabase.table("sessions").update({
            "current_phase": response_data.next_phase
        }).eq("id", request.session_id).execute()

    # Save tutor response to transcript
    supabase.table("transcripts").insert({
        "session_id": request.session_id,
        "speaker": "tutor",
        "text": response_data.text
    }).execute()

    return ChatResponse(
        response=response_data.text,
        history=result.all_messages()
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
