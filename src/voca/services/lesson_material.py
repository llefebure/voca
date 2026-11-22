"""Lesson material blocks: the typed, renderable primitives that make up a lesson.

A deliberately small, composable set — documents are *content, never types*: a
menu, a flyer, a listing or a reading passage are all `text` (markdown, tables
included) plus whatever scenario/dialogue/questions surround it. The planner
produces these; the UI renders each with its own distinct visual treatment; the
session stores them so a continued session can replay the lesson.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter


class ScenarioBlock(BaseModel):
    """Where, who, and why — the "setting the scene" card."""

    type: Literal["scenario"] = "scenario"
    setting: str = Field(description="Where the scene takes place")
    learner_role: str = Field(description="The role the learner plays")
    tutor_role: str = Field(description="The role the tutor plays")
    goal: str = Field(description="What a successful encounter looks like")


class TextBlock(BaseModel):
    """A document to show: a reading passage, a menu as a markdown table, a flyer…"""

    type: Literal["text"] = "text"
    title: str | None = Field(default=None, description="Optional display title")
    markdown: str = Field(description="Markdown body (paragraphs, tables, lists all fine)")


class DialogueTurn(BaseModel):
    speaker: Literal["tutor", "learner"]
    text: str = Field(description="The line; an empty string marks a learner gap to fill")


class DialogueBlock(BaseModel):
    """A scripted exchange; empty learner turns are the gaps the learner fills."""

    type: Literal["dialogue"] = "dialogue"
    turns: list[DialogueTurn]


class QuestionsBlock(BaseModel):
    type: Literal["questions"] = "questions"
    items: list[str] = Field(description="3-5 questions, literal recall up to opinion")


class TaskItem(BaseModel):
    task: str
    hint: str | None = Field(default=None, description="Optional nudge toward the target form")


class TasksBlock(BaseModel):
    type: Literal["tasks"] = "tasks"
    items: list[TaskItem] = Field(description="2-6 things to explain, describe, or produce")


class WordBankBlock(BaseModel):
    type: Literal["word_bank"] = "word_bank"
    items: list[str] = Field(description="3-8 target expressions shown as chips")


MaterialBlock = Annotated[
    ScenarioBlock | TextBlock | DialogueBlock | QuestionsBlock | TasksBlock | WordBankBlock,
    Field(discriminator="type"),
]

# One adapter per payload shape used across the app.
BLOCK_ADAPTER: TypeAdapter[MaterialBlock] = TypeAdapter(MaterialBlock)
MATERIAL_ADAPTER: TypeAdapter[list[MaterialBlock]] = TypeAdapter(list[MaterialBlock])

BLOCK_TYPE_NAMES: dict[str, str] = {
    "scenario": "Scenario",
    "text": "Text",
    "dialogue": "Dialogue",
    "questions": "Questions",
    "tasks": "Tasks",
    "word_bank": "Word bank",
}


def parse_material(raw: list[dict]) -> list[MaterialBlock]:
    """Validate already-stored material (defensive read path: drop invalid blocks)."""
    kept: list[MaterialBlock] = []
    for block in raw:
        try:
            kept.append(BLOCK_ADAPTER.validate_python(block, strict=False))
        except Exception:  # noqa: BLE001 - a bad stored block must not break rendering
            continue
    return kept


def filter_allowed(
    blocks: list[MaterialBlock], allowed: set[str]
) -> tuple[list[MaterialBlock], list[str]]:
    """Split blocks into (allowed, rejected) by block type."""
    kept = [b for b in blocks if b.type in allowed]
    dropped = [b.type for b in blocks if b.type not in allowed]
    return kept, dropped
