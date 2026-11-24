"""Panel content primitives: markdown only; escape decoding stays."""

from voca.services.panel_content import normalize_panel


def test_normalize_panel_decodes_escaped_newlines():
    """gemma emits literal \\n sequences inside tool-arg markdown (verified in
    stored data); they must decode into real line breaks so tables/paragraphs
    render."""
    panel = normalize_panel(
        "Hotel",
        "**Hotel Sol y Luna**\\n\\n| Hora | Act |\\n| :--- | :--- |\\n| 08:00 | Desayuno |",
    )
    assert "\\n" not in panel["markdown"]
    assert "\n\n" in panel["markdown"]
    assert panel["title"] == "Hotel"


def test_normalize_panel_defaults_a_blank_title():
    assert normalize_panel("", "# Carta")["title"] == "Panel"
    assert normalize_panel("  ", "# Carta")["title"] == "Panel"


def test_normalize_panel_keeps_markdown_verbatim_otherwise():
    panel = normalize_panel("Mi menú", "| Plato | Precio |\n| :--- | :--- |\n| Tacos | 60 |")
    assert panel["markdown"].startswith("| Plato |")
    assert "Tacos" in panel["markdown"]


def test_normalize_panel_supports_rich_markdown_shapes():
    """Lists, tables, headings — the model composes whatever it needs."""
    markdown = "## Desayuno\n\n- Huevos\n- Café\n\n> Nota: incluye pan"
    assert normalize_panel("Checklist", markdown)["markdown"] == markdown
