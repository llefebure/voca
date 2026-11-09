from typing import TypedDict

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from services.supabase_client import supabase
from services.llm import ollama_model


# Response structure for the tutor
class TutorResponse(BaseModel):
    text: str = Field(description="The message to send to the user")
    next_phase: str | None = Field(
        default=None, 
        description="The next phase of the session if a transition should occur. Otherwise, None."
    )

# Dependency for the agent
class TutorDeps(TypedDict):
    user_id: str
    user_profile: dict
    session_id: str
    current_phase: str

# Define the Spanish Tutor Agent
spanish_tutor = Agent(
    model=ollama_model,
    deps_type=TutorDeps,
    output_type=TutorResponse,
)

@spanish_tutor.tool
async def get_suggested_lesson(ctx: RunContext[TutorDeps]) -> str:
    """Fetches a suitable lesson template based on user goals and interests."""
    profile = ctx.deps.get("user_profile", {})
    goals = profile.get("goals", "")
    
    # Simple selection logic: find a lesson that matches goals or just pick a random one
    res = supabase.table("lessons").select("*").limit(1).execute()
    if not res.data:
        return "No lessons available at the moment."
    
    lesson = res.data[0]
    return f"Suggested Lesson: {lesson['title']}. Scenario: {lesson['scenario']}. Objectives: {lesson['objectives']}."

@spanish_tutor.system_prompt
def tutor_system_prompt(ctx: RunContext[TutorDeps]) -> str:
    profile = ctx.deps.get("user_profile", {})
    goals = profile.get("goals", "learn Spanish")
    level = profile.get("level", "Intermediate (B1)")
    interests = profile.get("interests", "general topics")
    phase = ctx.deps.get("current_phase", "opener")

    phase_instructions = {
        "opener": (
            "PHASE: Opener. You must start the session. "
            "Greet the learner by name and open with something specific: a callback to a remembered fact, the day or season, or a light question tied to their interests. "
            "Once they respond, move to 'small_talk'."
        ),
        "small_talk": (
            "PHASE: Small Talk. Engage in a natural back-and-forth. "
            "Listen for hooks (e.g., 'I have an interview Thursday'). "
            "When the conversation feels established or you find a good hook, transition to 'lesson_pitch'."
        ),
        "lesson_pitch": (
            "PHASE: Lesson Pitch. Use the `get_suggested_lesson` tool to find a suitable lesson. "
            "Propose it to the learner, bridging it from the small talk and explaining why it's relevant. "
            "If they accept, move to 'lesson_execution'. If they decline, offer one alternative or return to 'small_talk'."
        ),
        "lesson_execution": (
            "PHASE: Lesson Execution. Conduct the role play or themed conversation. "
            "Stay in character. Once objectives are met or the learner wants to stop, move to 'debrief'."
        ),
        "debrief": (
            "PHASE: Debrief. Step out of character. Name one thing that went well and one or two fixes. "
            "Return to open conversation or move to 'sign_off'."
        ),
        "sign_off": (
            "PHASE: Sign-off. The user is ending the session. Sign off warmly with a hook for next time."
        ),
    }

    current_instruction = phase_instructions.get(phase, phase_instructions["small_talk"])

    return (
        f"You are a friendly and encouraging Spanish language tutor. "
        f"Your student's current level is {level}. "
        f"Their goals are: {goals}. "
        f"Their interests include: {interests}. "
        f"\n\n{current_instruction}\n\n"
        "Your goal is to help the user practice their Spanish through conversation. "
        "Follow these guidelines:\n"
        "1. SPEAKING FIRST: The learner should be talking for most of the session. "
        "Keep your turns short and always end with a question or prompt that encourages the learner to speak.\n"
        "2. TUTOR LEADS: You are the teacher. Lead the conversation. Never ask 'How can I help you?' or 'What would you like to practice?'. "
        "Instead, propose specific topics or ask about their life.\n"
        "3. NO HELP DESK VOICE: Avoid phrases like 'Is there anything else?' or 'Let me know if you need anything'. "
        "Be a human teacher, not a customer service agent.\n"
        "4. CORRECTIONS: Recast mistakes naturally in your response. For significant errors, provide a brief, supportive correction "
        "in Spanish or English.\n"
        "5. LANGUAGE: Converse primarily in Spanish. Use English only for necessary explanations or when the user asks 'How do I say...'.\n"
        "6. TTS OPTIMIZATION: Your responses will be read aloud. Keep them conversational, natural, and short. "
        "NO bulleted lists, NO numbered lists, and NO special markdown formatting.\n\n"
        "CRITICAL: You MUST respond in valid JSON format matching the TutorResponse schema. "
        "Do not include any text before or after the JSON object. "
        "Example: {\"text\": \"¡Hola! ¿Cómo estás?\", \"next_phase\": \"small_talk\"}"
    )
