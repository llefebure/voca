"""Material shape normalization: the planner's output is coerced before validation.

gemma emits block payloads without the union tag (key-wrapped `{"scenario": {...}}`,
bare `{"setting": …}`) and uses alias names (`menu`/`passage` → `text`,
`rounds`/`goal_list` → `tasks`); `normalize_blocks` recovers all of them so the
retry loop only burns on real content problems.
"""

from voca.services.lesson_flow import validate_material
from voca.services.lesson_material import (
    BLOCK_ADAPTER,
    MATERIAL_ADAPTER,
    normalize_blocks,
)


def _kinds(raw: list[dict]) -> list[str]:
    return [BLOCK_ADAPTER.validate_python(block).type for block in normalize_blocks(raw)]


def test_key_wrapped_payloads_get_unwrapped_and_tagged():
    kinds = _kinds(
        [
            {
                "scenario": {
                    "goal": "Order a full meal",
                    "learner_role": "customer",
                    "tutor_role": "waiter",
                    "setting": "a taquería",
                }
            },
            {"text": {"title": "Carta", "markdown": "| Café | 1,2 € |"}},
            {"rounds": {"items": [{"task": "Di algo"}]}},
        ]
    )
    assert kinds == ["scenario", "text", "tasks"]


def test_alias_type_names_map_to_primitives():
    kinds = _kinds(
        [
            {"type": "menu", "title": "Carta", "markdown": "| X |"},
            {"type": "passage", "markdown": "Un día en el mercado…"},
            {"type": "goal_list", "items": [{"task": "Describe tu ciudad"}]},
            {"type": "script", "turns": [{"speaker": "tutor", "text": "¡Buenas!"}]},
        ]
    )
    assert kinds == ["text", "text", "tasks", "dialogue"]


def test_bare_payloads_infer_their_type_from_fields():
    kinds = _kinds(
        [
            {
                "setting": "a café",
                "learner_role": "customer",
                "tutor_role": "barista",
                "goal": "order",
            },
            {"markdown": "Un pasaje corto."},
            {"items": ["un cortado", "la cuenta"]},  # short non-question items: word bank
            {"items": ["¿Qué pide el cliente?"]},  # questions end in '?'
        ]
    )
    assert kinds == ["scenario", "text", "word_bank", "questions"]


def test_validated_list_roundtrip_through_the_adapter():
    parsed = MATERIAL_ADAPTER.validate_python(
        normalize_blocks(
            [
                {
                    "type": "scenario",
                    "setting": "s",
                    "learner_role": "l",
                    "tutor_role": "t",
                    "goal": "g",
                },
                {"type": "menu", "markdown": "# Carta"},
            ]
        )
    )
    assert [block.type for block in parsed] == ["scenario", "text"]


def test_word_bank_items_emitted_as_term_objects_get_flattened():
    """The model invents `{"term": …, "translation": …}` word-bank rows; flatten them."""
    blocks, _ = validate_material(
        "dialogue_gaps",
        [
            {
                "type": "word_bank",
                "items": [
                    {"term": "Agrio / Ácido", "translation": "Sour / Acidic"},
                    {"phrase": "Dulce"},
                    "Salado",
                ],
            }
        ],
    )
    assert blocks[0].items == ["Agrio / Ácido", "Dulce", "Salado"]


def test_tasks_items_emitted_as_plain_strings_get_wrapped():
    blocks, _ = validate_material(
        "sentence_sprint",
        [{"type": "tasks", "items": ["Di qué comiste ayer", {"task": "Pide la cuenta"}]}],
    )
    assert blocks[0].items[0].task == "Di qué comiste ayer"
    assert blocks[0].items[1].task == "Pide la cuenta"


def test_vocab_pair_items_in_a_tasks_block_are_retyped_as_word_bank():
    """gemma tags vocabulary rows `tasks` and gives them term/translation objects."""
    blocks, dropped = validate_material(
        "reading_discussion",
        [
            {"type": "text", "markdown": "passage"},
            {"type": "questions", "items": ["Q?"]},
            {
                "type": "tasks",
                "items": [
                    {"term": "quisiera…", "translation": "I would like…"},
                    {"term": "la cuenta", "translation": "the bill"},
                ],
            },
        ],
    )
    kinds = [block.type for block in blocks]
    assert kinds == ["text", "questions", "word_bank"]
    word_bank = blocks[2]
    assert word_bank.items == ["quisiera…", "la cuenta"]
    assert dropped == []


def test_double_escaped_newlines_in_text_survive_as_line_breaks():
    """gemma emits literal \\n sequences inside markdown (verified in stored data);
    they must decode into real line breaks so tables/paragraphs render."""
    blocks, _ = validate_material(
        "reading_discussion",
        [
            {
                "type": "text",
                "markdown": "**Hotel Sol y Luna**\\n\\n| Hora | Act |\\n| :--- | :--- |\\n| 08:00 | Desayuno |",
            },
            {"type": "questions", "items": ["¿Cómo fue el viaje?\\n¿Qué visitaste?"]},
        ],
    )
    markdown = blocks[0].markdown
    assert "\\n" not in markdown
    assert "\n\n" in markdown
    assert blocks[1].items[0].endswith("¿Qué visitaste?")
