from typing import NotRequired, TypedDict

from pydantic_ai import Agent, RunContext

from voca.services.languages import language_name
from voca.services.lesson_templates import template_name, template_structure
from voca.services.llm import ollama_model


# Dependency for the agent
class TutorDeps(TypedDict):
    user_id: str
    user_profile: dict
    session_id: str
    # The planned lesson for this session ({lesson, opening_hook, cards}) or None.
    session_plan: NotRequired[dict | None]


# The language tutor: the language being learned comes from the user's profile
# (`target_language`), never hardcoded. When a session plan exists, the tutor
# leads the conversation through that lesson.
tutor_agent = Agent(
    model=ollama_model,
    deps_type=TutorDeps,
)


@tutor_agent.instructions
def tutor_system_prompt(ctx: RunContext[TutorDeps]) -> str:
    profile = ctx.deps.get("user_profile", {})
    language = language_name(profile.get("target_language"))
    goals = profile.get("goals", f"learn {language}")
    level = profile.get("level", "Intermediate (B1)")
    interests = profile.get("interests", "general topics")

    prompt = (
        f"You are a friendly and encouraging {language} language tutor. "
        f"Your student's current level is {level}. "
        f"Their goals are: {goals}. "
        f"Their interests include: {interests}. "
        "\n\n"
        f"Your goal is to help the user practice their {language} through conversation. "
        "Follow these guidelines:\n"
        "1. SPEAKING FIRST: The learner should be talking for most of the session. "
        "Keep your turns short and always end with a question or prompt that encourages the learner to speak.\n"
        "2. TUTOR LEADS: You are the teacher. Lead the conversation. Never ask 'How can I help you?' or 'What would you like to practice?'. "
        "Instead, propose specific topics or ask about their life.\n"
        "3. NO HELP DESK VOICE: Avoid phrases like 'Is there anything else?' or 'Let me know if you need anything'. "
        "Be a human teacher, not a customer service agent.\n"
        "4. CORRECTIONS: Recast mistakes naturally in your response. For significant errors, provide a brief, supportive correction "
        f"in {language} or English.\n"
        f"5. LANGUAGE: Converse primarily in {language}. Use English only for necessary explanations or when the user asks 'How do I say...'.\n"
        "6. TTS OPTIMIZATION: Your responses will be read aloud. Keep them conversational, natural, and short. "
        "NO bulleted lists, NO numbered lists, and NO special markdown formatting."
    )

    plan = ctx.deps.get("session_plan")
    if plan and plan.get("lesson"):
        lesson = plan["lesson"]
        lines = [
            "",
            "TODAY'S LESSON — guide the conversation through it:",
            f"- Template: {template_name(lesson.get('template'))}",
            f"- Structure: {template_structure(lesson.get('template'))}",
            f"- Topic: {lesson.get('topic', '')}",
        ]
        if lesson.get("scenario"):
            lines.append(f"- Scenario: {lesson['scenario']}")
        objectives = lesson.get("objectives") or []
        if objectives:
            lines.append("- Objectives: " + "; ".join(objectives))
        if plan.get("opening_hook"):
            lines.append(
                "- Opening hook (use it, reworded, when the conversation is just starting): "
                + plan["opening_hook"]
            )
        for card in plan.get("cards") or []:
            front, back = card.get("front", ""), card.get("back", "")
            if front or back:
                lines.append(f"- Target to weave in: {front} → {back}")
        prompt += "\n".join(lines)

    return prompt
