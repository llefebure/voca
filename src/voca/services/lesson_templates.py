"""Lesson templates: structural outlines the planner instantiates per session.

There is no lesson bank — lessons are generated on the fly. The session
planner picks a template id and fills in a concrete topic, scenario and
objectives tailored to the learner; the result is stored in `sessions.plan`.
Adding a lesson format means adding one entry here.
"""

from typing import TypedDict


class LessonTemplate(TypedDict):
    id: str
    name: str
    structure: str


LESSON_TEMPLATES: list[LessonTemplate] = [
    {
        "id": "role_play",
        "name": "Role Play",
        "structure": (
            "Set up a concrete scenario with defined roles, then stay in character. "
            "Introduce a small complication midway, and close by reviewing the key "
            "phrases the learner needed."
        ),
    },
    {
        "id": "reading_comprehension",
        "name": "Reading Comprehension",
        "structure": (
            "The tutor reads a short passage (written for the learner's level) aloud. "
            "Ask 3-5 questions about it, from literal recall up to inference, and "
            "finish by asking the learner's opinion of the passage."
        ),
    },
    {
        "id": "free_conversation",
        "name": "Free Conversation",
        "structure": (
            "Open conversation on a topic the learner cares about. The tutor "
            "deliberately steers toward the target vocabulary and nudges the learner "
            "to use it naturally."
        ),
    },
]

_TEMPLATE_IDS = ", ".join(t["id"] for t in LESSON_TEMPLATES)


def template_ids() -> str:
    """Comma-separated template ids for schema/prompt descriptions."""
    return _TEMPLATE_IDS


def template_catalog() -> str:
    """Compact catalog text injected into the planner prompt."""
    return "\n".join(f"- {t['id']}: {t['name']} — {t['structure']}" for t in LESSON_TEMPLATES)


def template_name(template_id: str | None) -> str:
    """Display name for a template id (its id, when unknown)."""
    for template in LESSON_TEMPLATES:
        if template["id"] == template_id:
            return template["name"]
    return template_id or "Free-form session"


def template_structure(template_id: str | None) -> str:
    """Phase outline for a template id ('' when unknown)."""
    for template in LESSON_TEMPLATES:
        if template["id"] == template_id:
            return template["structure"]
    return ""
