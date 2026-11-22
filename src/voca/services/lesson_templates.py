"""Lesson templates: structural outlines the planner instantiates mid-conversation.

There is no lesson bank — lessons are generated on the fly after a stretch of
small talk (or when the learner asks for one). The planner picks a template and
produces the typed material blocks it requires; the result is stored as a lesson
instance in `sessions.lessons`. Casual chat is not a template — it is the loop's
background state. Adding a lesson format means adding one entry here.

Planned v2 templates (not implementable yet; recorded here so the taxonomy is
visible): opinion_debate, interview (tutor as journalist), news_reaction,
pronunciation_drill (TTS minimal pairs), image_description (needs image
generation), song_lyrics.
"""

from typing import TypedDict


class LessonTemplate(TypedDict):
    id: str
    name: str
    minutes: str
    # Block primitives the planner must / may produce. `required` must all be
    # present in the generated material; `optional` are allowed extras.
    required_blocks: tuple[str, ...]
    optional_blocks: tuple[str, ...]
    structure: str


LESSON_TEMPLATES: list[LessonTemplate] = [
    {
        "id": "role_play",
        "name": "Role Play",
        "minutes": "5-10",
        "required_blocks": ("scenario",),
        "optional_blocks": ("text", "word_bank"),
        "structure": (
            "Set the scene with defined roles, stay in character. Introduce one small "
            "complication midway, and close by reviewing the key phrases the learner "
            "needed. Document props (a menu as a markdown table, a flyer, a booking "
            "confirmation) are `text` blocks shown alongside the scene."
        ),
    },
    {
        "id": "reading_discussion",
        "name": "Reading + Discussion",
        "minutes": "5-10",
        "required_blocks": ("text", "questions"),
        "optional_blocks": ("word_bank",),
        "structure": (
            "The learner reads a short passage (written for their level; the tutor reads "
            "it aloud on request), answers 3-5 questions from literal recall up to "
            "inference, and finishes by giving their opinion of the passage."
        ),
    },
    {
        "id": "dialogue_gaps",
        "name": "Dialogue Gaps",
        "minutes": "5-8",
        "required_blocks": ("dialogue",),
        "optional_blocks": ("word_bank",),
        "structure": (
            "Preview the target phrases from the word bank, then the learner fills the "
            "dialogue's empty learner turns line by line; finish by replaying one "
            "exchange freely without looking."
        ),
    },
    {
        "id": "story_telling",
        "name": "Storytelling",
        "minutes": "5-10",
        "required_blocks": ("scenario",),
        "optional_blocks": ("word_bank",),
        "structure": (
            "Elicit a narration from the story-starter scene drawing on the learner's real "
            "experiences, recast tense and connector mistakes naturally, and have the "
            "learner retell one improved bit."
        ),
    },
    {
        "id": "explain_describe",
        "name": "Explain & Describe",
        "minutes": "5-8",
        "required_blocks": ("tasks",),
        "optional_blocks": ("word_bank",),
        "structure": (
            "Work through 2-4 describe/explain tasks with follow-up questions; the tutor "
            "nudges toward richer vocabulary without taking the floor back."
        ),
    },
    {
        "id": "sentence_sprint",
        "name": "Sentence Sprint",
        "minutes": "3-6",
        "required_blocks": ("tasks",),
        "optional_blocks": ("word_bank",),
        "structure": (
            "4-6 quick-fire production tasks, one target structure each; brisk pacing, "
            "the tutor keeps score and corrects on the fly, no long explanations."
        ),
    },
]

_TEMPLATE_IDS = ", ".join(t["id"] for t in LESSON_TEMPLATES)


def template_ids() -> str:
    """Comma-separated template ids for schema/prompt descriptions."""
    return _TEMPLATE_IDS


def find_template(template_id: str | None) -> LessonTemplate | None:
    for template in LESSON_TEMPLATES:
        if template["id"] == template_id:
            return template
    return None


def template_name(template_id: str | None) -> str:
    """Display name for a template id (its id, when unknown)."""
    return find_template(template_id)["name"] if find_template(template_id) else "Lesson"


def template_structure(template_id: str | None) -> str:
    """Phase outline for a template id ('' when unknown)."""
    return find_template(template_id)["structure"] if find_template(template_id) else ""


def template_minutes(template_id: str | None) -> str:
    """Time hint for a template id ('' when unknown)."""
    return find_template(template_id)["minutes"] if find_template(template_id) else ""


def allowed_blocks(template_id: str | None) -> set[str] | None:
    """Block types a template's material may contain; None for unknown templates."""
    template = find_template(template_id)
    if template is None:
        return None
    return {*template["required_blocks"], *template["optional_blocks"]}


def template_catalog() -> str:
    """Compact catalog text injected into the planner prompt."""
    return "\n".join(
        f"- {t['id']}: {t['name']} ({t['minutes']} min) — required blocks: "
        f"{', '.join(t['required_blocks'])}; optional: {', '.join(t['optional_blocks']) or '—'}. "
        f"{t['structure']}"
        for t in LESSON_TEMPLATES
    )
