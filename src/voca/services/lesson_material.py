"""Lesson material blocks: the typed, renderable primitives that make up a lesson.

A deliberately small, composable set — documents are *content, never types*: a
menu, a flyer, a listing or a reading passage are all `text` (markdown, tables
included) plus whatever scenario/dialogue/questions surround it. The planner
produces these; the UI renders each with its own distinct visual treatment; the
session stores them so a continued session can replay the lesson.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, TypeAdapter


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


# The model sometimes emits block payloads without the `type` tag — key-wrapped
# ({"scenario": {...}}) or bare ({"setting": ...}) — or uses alias names. Coerce
# to the tagged shape before union validation; real content problems still fail.
_TYPE_ALIASES: dict[str, str] = {
    "scenario": "scenario",
    "text": "text",
    "passage": "text",
    "menu": "text",
    "document": "text",
    "props": "text",
    "flyer": "text",
    "dialogue": "dialogue",
    "script": "dialogue",
    "questions": "questions",
    "task": "tasks",
    "tasks": "tasks",
    "rounds": "tasks",
    "goal_list": "tasks",
    "word_bank": "word_bank",
}


def _tag_from_key_or_fields(block: dict[str, Any]) -> str | None:
    if len(block) == 1:
        ((key, _value),) = block.items()
        if key in _TYPE_ALIASES:
            return _TYPE_ALIASES[key]
    if "setting" in block:
        return "scenario"
    if "turns" in block:
        return "dialogue"
    if "markdown" in block or ("title" in block and "items" not in block):
        return "text"
    if "items" in block:
        items = block["items"]
        first = items[0] if items else None
        if isinstance(first, dict):
            # Vocabulary-pair objects ({"term": …, "translation": …}) are a word
            # bank however they get tagged; only task-shaped objects are tasks.
            if _has_vocab_keys(first):
                return "word_bank"
            return "tasks"
        if items and all(not str(item).strip().endswith("?") for item in items):
            return "word_bank"
        return "questions"
    return None


def _has_vocab_keys(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    return any(key in item for key in ("term", "phrase", "word", "es"))


def normalize_block(block: Any) -> Any:
    """Coerce a model-emitted material block into the tagged, union-ready shape."""
    if not isinstance(block, dict):
        return block
    # Key-wrapped payloads first: {"rounds": {"items": …}} / {"text": {"markdown": …}}.
    if len(block) == 1:
        ((key, value),) = block.items()
        if isinstance(value, dict) and key in _TYPE_ALIASES:
            block = dict(value)
    raw_type = block.get("type")
    if not isinstance(raw_type, str) or raw_type not in _TYPE_ALIASES:
        inferred = _tag_from_key_or_fields(block)
        if inferred is None:
            inferred = raw_type if isinstance(raw_type, str) else None
            if inferred is None:
                return block
        block = {**block, "type": inferred}
    else:
        block = {**block, "type": _TYPE_ALIASES[raw_type]}
    payload, retyped = _coerce_items(block, str(block["type"]))
    # _coerce_items may retype the block; the payload's original ``type`` key
    # must not shadow the new tag in the spread.
    return {"type": retyped, **{key: value for key, value in payload.items() if key != "type"}}


def _item_term(item: dict[str, Any]) -> Any:
    """A readable term from a model-invented vocab-pair object."""
    return (
        item.get("term")
        or item.get("phrase")
        or item.get("word")
        or item.get("es")
        or next((v for v in item.values() if isinstance(v, str) and v.strip()), str(item))
    )


def _coerce_items(payload: dict[str, Any], block_type: str) -> tuple[dict[str, Any], str]:
    """Flatten model-invented item shapes into each block's declared schema.

    Vocabulary-pair objects are always a word bank (retyping a miscategorized
    ``tasks`` block); strings inside a tasks block are wrapped into task items.
    """
    items = payload.get("items")
    if not items:
        return payload, block_type
    if any(_has_vocab_keys(item) for item in items):
        # Vocabulary-pair objects: flatten to plain terms and retype as a word
        # bank however the model tagged the block.
        return (
            {
                **payload,
                "items": [
                    _item_term(item) if isinstance(item, dict) else str(item) for item in items
                ],
            },
            "word_bank",
        )
    if block_type == "tasks" and any(isinstance(item, str) for item in items):
        payload = {
            **payload,
            "items": [{"task": str(item)} if isinstance(item, str) else item for item in items],
        }
    return payload, block_type


def normalize_blocks(blocks: Any) -> Any:
    """Apply `normalize_block` over a material list (pass-through otherwise)."""
    if isinstance(blocks, list):
        return [normalize_block(block) for block in blocks]
    return blocks


MaterialBlock = Annotated[
    ScenarioBlock | TextBlock | DialogueBlock | QuestionsBlock | TasksBlock | WordBankBlock,
    Field(discriminator="type"),
]

# The planner's material field: model-tolerant (untagged/aliased shapes normalized).
MaterialList = Annotated[list[MaterialBlock], BeforeValidator(normalize_blocks)]

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
    """Validate stored/planner material (defensive read path: drop invalid blocks).

    Normalization runs here too, so restored sessions and any caller passing raw
    model-shaped dicts get the same tolerance as the planner's live validation.
    """
    kept: list[MaterialBlock] = []
    for block in raw:
        try:
            kept.append(BLOCK_ADAPTER.validate_python(normalize_block(block), strict=False))
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
