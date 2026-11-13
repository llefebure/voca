"""Endpoint tests for /sessions/* and /translate — fully offline."""

import httpx
import pytest
from fsrs import Rating

from voca import main as voca_main
from voca.agents.post_session_agent import (
    CardCandidate,
    CardGrade,
    PostSessionResult,
    ProfileUpdates,
    SessionRecap,
)
from voca.agents.session_planner_agent import LessonSpec, SessionPlan
from voca.services.srs import new_card_state

AUTH = {"Authorization": "Bearer valid-token"}


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=voca_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture
def analyst_result() -> PostSessionResult:
    return PostSessionResult(
        new_cards=[
            CardCandidate(
                type="phrase",
                front="I am exhausted",
                back="estoy agotado",
                source_sentence="estoy muy agotado",
                reason="learner asked for it",
            )
        ],
        reviewed_cards=[CardGrade(card_id="card-1", outcome="pass")],
        recap=SessionRecap(
            positives=["good vocabulary"],
            key_corrections=["ser vs estar"],
            next_time_preview="restaurant role play",
        ),
        profile_updates=ProfileUpdates(interests="architecture"),
    )


@pytest.mark.asyncio
async def test_start_session_creates_active_session(client, fake_supabase):
    response = await client.post("/sessions/start", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"

    inserted = fake_supabase.inserted_rows("sessions")
    assert inserted == [{"user_id": "user-1", "status": "active", "language": "es"}]
    # Practice stamps "latest practiced": user_languages row + profile pointer.
    upserts = fake_supabase.upserted_rows("user_languages")
    assert len(upserts) == 1
    assert upserts[0]["user_id"] == "user-1"
    assert upserts[0]["language"] == "es"
    assert upserts[0]["last_practiced_at"]
    assert fake_supabase.updated_rows("profiles") == [
        {"values": {"target_language": "es"}, "filters": {"id": "user-1"}}
    ]


@pytest.mark.asyncio
async def test_start_session_stamps_profile_language(client, fake_supabase):
    """The session inherits the language the profile points at — even non-default."""
    fake_supabase.results[("profiles", "select")] = [
        {"id": "user-1", "target_language": "fr"}
    ]
    response = await client.post("/sessions/start", headers=AUTH)
    assert response.status_code == 200
    assert fake_supabase.inserted_rows("sessions") == [
        {"user_id": "user-1", "status": "active", "language": "fr"}
    ]
    assert fake_supabase.upserted_rows("user_languages")[0]["language"] == "fr"
    assert fake_supabase.updated_rows("profiles") == [
        {"values": {"target_language": "fr"}, "filters": {"id": "user-1"}}
    ]


@pytest.mark.asyncio
async def test_list_sessions(client, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "status": "completed", "recap": {"a": 1}, "language": "es"}
    ]
    response = await client.get("/sessions", headers=AUTH)
    assert response.status_code == 200
    sessions = response.json()["sessions"]
    assert sessions == [
        {
            "session_id": "sess-1",
            "status": "completed",
            "created_at": None,
            "end_time": None,
            "recap": {"a": 1},
            "language": "es",
        }
    ]
    # Unfiltered list does not scope by language.
    assert "language" not in fake_supabase.select_filters_rows("sessions")[-1]


@pytest.mark.asyncio
async def test_list_sessions_filters_by_language(client, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "status": "active", "language": "es"}
    ]
    response = await client.get("/sessions", params={"language": "es"}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["sessions"][0]["language"] == "es"
    assert fake_supabase.select_filters_rows("sessions")[-1] == {
        "user_id": "user-1",
        "language": "es",
    }


@pytest.mark.asyncio
async def test_end_session_requires_existing_session(client, fake_supabase):
    response = await client.post("/sessions/end", params={"session_id": "missing"}, headers=AUTH)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_end_session_inserts_cards_and_updates_srs(
    client, fake_supabase, analyst_result, monkeypatch
):
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "active", "language": "es"}
    ]
    fake_supabase.results[("transcripts", "select")] = [
        {"speaker": "user", "text": "¿Cómo digo 'I am exhausted'?"}
    ]
    fake_supabase.results[("cards", "select")] = [
        {"id": "card-1", "front": "exhausted", "fsrs_data": new_card_state()}
    ]

    async def fake_run(_prompt, deps=None):
        assert deps["transcript"], "analyst must receive the transcript"
        assert any(card["id"] == "card-1" for card in deps["due_cards"])
        assert deps["target_language"] == "es"
        return type("R", (), {"output": analyst_result})()

    monkeypatch.setattr(voca_main.post_session_agent, "run", fake_run)

    response = await client.post("/sessions/end", params={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["new_cards_count"] == 1
    assert body["recap"]["next_time_preview"] == "restaurant role play"
    # "Words you spoke" is computed from the transcript, not invented by the model.
    assert body["recap"]["user_word_count"] == 5

    # New cards: labelled `new`, FSRS state in its own column, due immediately,
    # and stamped with the session's language.
    inserted_cards = fake_supabase.inserted_rows("cards")
    assert len(inserted_cards) == 1
    card_row = inserted_cards[0]
    assert card_row["state"] == "new"
    assert card_row["fsrs_data"]  # FSRS state JSON persisted in the dedicated column
    assert card_row["next_review"]
    assert card_row["back"] == "estoy agotado"
    assert card_row["language"] == "es"

    # The reviewed card's FSRS state advanced beyond the fresh state.
    card_updates = [
        update for update in fake_supabase.updated_rows("cards") if "fsrs_data" in update["values"]
    ]
    assert len(card_updates) == 1
    assert card_updates[0]["values"]["next_review"]
    assert card_updates[0]["values"]["last_review"]

    session_updates = fake_supabase.updated_rows("sessions")
    assert any(update["values"].get("status") == "completed" for update in session_updates)
    assert any("recap" in update["values"] for update in session_updates)
    # Per-language profile upgrades go to user_languages, not profiles.
    assert fake_supabase.upserted_rows("user_languages") == [
        {"user_id": "user-1", "language": "es", "interests": "architecture"}
    ]
    assert fake_supabase.updated_rows("profiles") == []


@pytest.mark.asyncio
async def test_end_session_skips_not_attempted_cards(client, fake_supabase, monkeypatch):
    result = PostSessionResult(
        new_cards=[],
        reviewed_cards=[CardGrade(card_id="card-1", outcome="not_attempted")],
        recap=SessionRecap(
            positives=[],
            key_corrections=[],
            next_time_preview="tomorrow",
        ),
        profile_updates=ProfileUpdates(),
    )

    async def fake_run(_prompt, deps=None):
        return type("R", (), {"output": result})()

    monkeypatch.setattr(voca_main.post_session_agent, "run", fake_run)
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "active"}
    ]
    fake_supabase.results[("transcripts", "select")] = []

    response = await client.post("/sessions/end", params={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    assert fake_supabase.inserted_rows("cards") == []
    # Only the completion update happened; no card/profile/recap updates.
    assert fake_supabase.updated_rows("cards") == []
    assert fake_supabase.updated_rows("profiles") == []
    assert fake_supabase.upserted_rows("user_languages") == []


@pytest.mark.asyncio
async def test_end_session_uses_session_language(client, fake_supabase, monkeypatch):
    """Legacy-free sessions carry their own language: due cards and stamps follow it."""
    result = PostSessionResult(
        new_cards=[],
        reviewed_cards=[],
        recap=SessionRecap(positives=[], key_corrections=[], next_time_preview="next"),
        profile_updates=ProfileUpdates(level="B2"),
    )

    async def fake_run(_prompt, deps=None):
        assert deps["target_language"] == "fr"
        # Grading only matches cards in the session's language.
        return type("R", (), {"output": result})()

    monkeypatch.setattr(voca_main.post_session_agent, "run", fake_run)
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "active", "language": "fr"}
    ]
    fake_supabase.results[("transcripts", "select")] = []

    response = await client.post("/sessions/end", params={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    assert fake_supabase.select_filters_rows("cards")[-1] == {
        "user_id": "user-1",
        "language": "fr",
    }
    assert fake_supabase.upserted_rows("user_languages") == [
        {"user_id": "user-1", "language": "fr", "level": "B2"}
    ]


@pytest.mark.asyncio
async def test_plan_session_stores_plan(client, fake_supabase, monkeypatch):
    plan = SessionPlan(
        lesson=LessonSpec(
            template="role_play",
            topic="At the pharmacy",
            scenario="Pharmacist and customer",
            objectives=["describe symptoms"],
        ),
        card_ids=["card-1"],
        opening_hook="¡Hola Alex!",
    )

    async def fake_run(_prompt, deps=None):
        assert deps["user_profile"]["goals"] == "business Spanish"
        # The planner only sees compact rows (no FSRS state) — selection is by ID,
        # and there is no lesson bank to pass in.
        assert deps["due_cards"] == [{"id": "card-1", "front": "exhausted", "back": "agotado"}]
        assert "available_lessons" not in deps
        return type("R", (), {"output": plan})()

    monkeypatch.setattr(voca_main.session_planner_agent, "run", fake_run)
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "active"}
    ]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1", "goals": "business Spanish"}]
    fake_supabase.results[("cards", "select")] = [
        {"id": "card-1", "front": "exhausted", "back": "agotado", "fsrs_data": new_card_state()}
    ]

    response = await client.post("/sessions/plan", params={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["opening_hook"] == "¡Hola Alex!"
    assert body["lesson"]["template"] == "role_play"
    # Selected IDs were resolved into stored card content for /chat to consume.
    assert body["cards"] == [{"id": "card-1", "front": "exhausted", "back": "agotado"}]
    plan_update = fake_supabase.updated_rows("sessions")[0]
    assert plan_update["values"]["plan"]["lesson"]["topic"] == "At the pharmacy"


@pytest.mark.asyncio
async def test_plan_rejects_ended_session(client, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "completed"}
    ]
    response = await client.post("/sessions/plan", params={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_end_session_rejects_already_ended(client, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "completed"}
    ]
    response = await client.post("/sessions/end", params={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_translate_uses_the_model(client, monkeypatch):
    async def fake_run(_prompt, **_kwargs):
        return type("R", (), {"output": "Hello"})()

    monkeypatch.setattr(voca_main.translator_agent, "run", fake_run)
    response = await client.post(
        "/translate", json={"text": "hola", "source_lang": "es", "target_lang": "en"}
    )
    assert response.status_code == 200
    assert response.json() == {"translation": "Hello"}


def test_rating_map_is_used_for_graded_outcomes():
    from voca.services.srs import VOCA_RATING_MAP

    assert VOCA_RATING_MAP.get("not_attempted") is None  # unknown outcomes are skipped
    assert VOCA_RATING_MAP.get("pass") == Rating.Good


# --- Effective profile + language-scoped due cards -------------------------------


def test_effective_profile_overlays_user_language(fake_supabase):
    """The user_languages row wins over the profile for level/goals/interests."""
    fake_supabase.results[("profiles", "select")] = [
        {"id": "user-1", "level": "A2", "goals": "global goals", "interests": "i0"}
    ]
    fake_supabase.results[("user_languages", "select")] = [
        {"level": "B1", "goals": "es goals", "interests": "es interests"}
    ]

    effective = voca_main.fetch_effective_profile("user-1", "es")

    assert effective["target_language"] == "es"  # pinned to the requested language
    assert effective["level"] == "B1"
    assert effective["goals"] == "es goals"
    assert effective["interests"] == "es interests"
    assert fake_supabase.select_filters_rows("user_languages")[-1] == {
        "user_id": "user-1",
        "language": "es",
    }


def test_effective_profile_partial_overlay_keeps_profile_fields(fake_supabase):
    fake_supabase.results[("profiles", "select")] = [
        {"id": "user-1", "level": "A2", "goals": "global goals"}
    ]
    fake_supabase.results[("user_languages", "select")] = [{"goals": "fr goals"}]

    effective = voca_main.fetch_effective_profile("user-1", "fr")

    assert effective["target_language"] == "fr"
    assert effective["level"] == "A2"  # no row value → profile field kept
    assert effective["goals"] == "fr goals"
    assert "interests" not in effective  # absent from both profile and row


def test_effective_profile_without_row_falls_back_to_profile(fake_supabase):
    fake_supabase.results[("profiles", "select")] = [
        {"id": "user-1", "target_language": "es", "level": "B1"}
    ]

    # No language requested: legacy path falls back to the profile's pointer.
    effective = voca_main.fetch_effective_profile("user-1", None)
    assert effective["target_language"] == "es"
    assert effective["level"] == "B1"
    # A brand-new language has no user_languages row yet: defaults apply everywhere.
    effective = voca_main.fetch_effective_profile("user-1", "pt")
    assert effective["target_language"] == "pt"
    assert effective["level"] == "B1"


def test_fetch_due_cards_scopes_by_language(fake_supabase):
    voca_main.fetch_due_cards("user-1", "fr")
    assert fake_supabase.select_filters_rows("cards")[-1] == {
        "user_id": "user-1",
        "language": "fr",
    }

    # Without a language, no filter is applied (callsite decides the scope).
    voca_main.fetch_due_cards("user-1")
    assert fake_supabase.select_filters_rows("cards")[-1] == {"user_id": "user-1"}
