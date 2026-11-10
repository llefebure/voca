"""Endpoint tests for /sessions/* and /translate — fully offline."""

import httpx
import pytest
from fsrs import Rating

from voca import main as voca_main
from voca.agents.post_session_agent import (
    CardCandidate,
    CardGrade,
    PostSessionResult,
    SessionRecap,
)
from voca.agents.session_planner_agent import PlannedCard, SessionPlan
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
            time_spoken="12 minutes",
            lesson_completed=True,
            positives=["good vocabulary"],
            key_corrections=["ser vs estar"],
            next_time_preview="restaurant role play",
        ),
        profile_updates={"interests": "architecture"},
    )


@pytest.mark.asyncio
async def test_start_session_creates_active_session(client, fake_supabase):
    response = await client.post("/sessions/start", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "active"

    inserted = fake_supabase.inserted_rows("sessions")
    assert inserted == [{"user_id": "user-1", "status": "active"}]


@pytest.mark.asyncio
async def test_list_sessions(client, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "status": "completed", "recap": {"a": 1}}
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
        }
    ]


@pytest.mark.asyncio
async def test_end_session_requires_existing_session(client, fake_supabase):
    response = await client.post("/sessions/end", params={"session_id": "missing"}, headers=AUTH)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_end_session_inserts_cards_and_updates_srs(
    client, fake_supabase, analyst_result, monkeypatch
):
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "active"}
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
        return type("R", (), {"output": analyst_result})()

    monkeypatch.setattr(voca_main.post_session_agent, "run", fake_run)

    response = await client.post("/sessions/end", params={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["new_cards_count"] == 1
    assert body["recap"]["next_time_preview"] == "restaurant role play"

    # New cards: labelled `new`, FSRS state in its own column, due immediately.
    inserted_cards = fake_supabase.inserted_rows("cards")
    assert len(inserted_cards) == 1
    card_row = inserted_cards[0]
    assert card_row["state"] == "new"
    assert card_row["fsrs_data"]  # FSRS state JSON persisted in the dedicated column
    assert card_row["next_review"]
    assert card_row["back"] == "estoy agotado"

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
    assert fake_supabase.updated_rows("profiles") == [
        {"values": {"interests": "architecture"}, "filters": {"id": "user-1"}}
    ]


@pytest.mark.asyncio
async def test_end_session_skips_not_attempted_cards(client, fake_supabase, monkeypatch):
    result = PostSessionResult(
        new_cards=[],
        reviewed_cards=[CardGrade(card_id="card-1", outcome="not_attempted")],
        recap=SessionRecap(
            time_spoken="1 minute",
            lesson_completed=False,
            positives=[],
            key_corrections=[],
            next_time_preview="tomorrow",
        ),
        profile_updates={},
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


@pytest.mark.asyncio
async def test_plan_session_stores_plan(client, fake_supabase, monkeypatch):
    plan = SessionPlan(
        suggested_lesson_id="lesson-1",
        target_cards=[
            PlannedCard(card_id="card-1", content="Revenue terms", reason="due this session")
        ],
        opening_hook="¡Hola Alex!",
    )

    async def fake_run(_prompt, deps=None):
        assert deps["user_profile"]["goals"] == "business Spanish"
        return type("R", (), {"output": plan})()

    monkeypatch.setattr(voca_main.session_planner_agent, "run", fake_run)
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "active"}
    ]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1", "goals": "business Spanish"}]
    fake_supabase.results[("cards", "select")] = []
    fake_supabase.results[("lessons", "select")] = []

    response = await client.post("/sessions/plan", params={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["opening_hook"] == "¡Hola Alex!"
    plan_update = fake_supabase.updated_rows("sessions")[0]
    assert plan_update["values"]["plan"]["suggested_lesson_id"] == "lesson-1"


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
