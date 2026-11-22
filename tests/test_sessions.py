"""Endpoint tests for /sessions/* and /translate — fully offline."""

import httpx
import pytest
from fsrs import Rating

from voca import main as voca_main
from voca.agents.lesson_grader_agent import CardGrade as TargetGrade
from voca.agents.lesson_grader_agent import LessonGrades, LessonSummary
from voca.agents.post_session_agent import (
    CardCandidate,
    CardGrade,
    PostSessionResult,
    ProfileUpdates,
    SessionRecap,
)
from voca.services.lesson_flow import LessonSpec, new_lesson
from voca.services.srs import new_card_state

AUTH = {"Authorization": "Bearer valid-token"}


def active(lessons: list[dict] | None = None) -> dict:
    row = {"id": "sess-1", "user_id": "user-1", "status": "active", "language": "es"}
    if lessons is not None:
        row["lessons"] = lessons
    return row


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
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1", "target_language": "fr"}]
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
async def test_list_sessions_paginates_limit_offset_and_total(client, fake_supabase):
    """limit/offset slice the list; total carries the full row count, not the page."""
    fake_supabase.results[("sessions", "select")] = [
        {"id": f"sess-{i:03d}", "status": "completed", "language": "es"} for i in range(105)
    ]
    response = await client.get("/sessions", params={"limit": 10, "offset": 100}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert [s["session_id"] for s in body["sessions"]] == [f"sess-{i:03d}" for i in range(100, 105)]
    assert body["total"] == 105
    assert fake_supabase.select_ranges_rows("sessions")[-1] == (100, 109)


@pytest.mark.asyncio
async def test_list_sessions_defaults_and_cap(client, fake_supabase):
    """No params → default page (50); limit is capped at 100, offset floors at 0."""
    fake_supabase.results[("sessions", "select")] = [
        {"id": f"sess-{i:03d}", "status": "completed", "language": "es"} for i in range(105)
    ]
    response = await client.get("/sessions", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert len(body["sessions"]) == 50
    assert body["total"] == 105
    assert fake_supabase.select_ranges_rows("sessions")[-1] == (0, 49)

    # Cap: an oversized limit behaves like 100.
    response = await client.get("/sessions", params={"limit": 500}, headers=AUTH)
    assert response.status_code == 200
    assert fake_supabase.select_ranges_rows("sessions")[-1] == (0, 99)

    # A negative offset floors to the first page.
    response = await client.get("/sessions", params={"offset": -50}, headers=AUTH)
    assert response.status_code == 200
    assert fake_supabase.select_ranges_rows("sessions")[-1] == (0, 49)


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
    response = await client.post("/sessions/end", json={"session_id": "missing"}, headers=AUTH)
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

    response = await client.post("/sessions/end", json={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["new_cards_count"] == 1
    assert body["recap"]["next_time_preview"] == "restaurant role play"
    # "Words you spoke" is computed from the transcript, not invented by the model.
    assert body["recap"]["user_word_count"] == 5
    # The recap always carries `new_cards` so the recap page need not re-query cards.
    assert body["recap"]["new_cards"] == [
        {"type": "phrase", "front": "I am exhausted", "back": "estoy agotado"}
    ]
    # New cards: FSRS state in its own column, due immediately,
    # and stamped with the session's language.
    inserted_cards = fake_supabase.inserted_rows("cards")
    assert len(inserted_cards) == 1
    card_row = inserted_cards[0]
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

    # Each graded card leaves an append-only review log row (positive recalls,
    # review activity over time — fsrs_data keeps no counts).
    review_rows = fake_supabase.inserted_rows("card_reviews")
    assert len(review_rows) == 1
    assert review_rows[0]["card_id"] == "card-1"
    assert review_rows[0]["user_id"] == "user-1"
    assert review_rows[0]["session_id"] == "sess-1"
    assert review_rows[0]["language"] == "es"
    assert review_rows[0]["rating"] == int(Rating.Good)
    assert review_rows[0]["reviewed_at"]

    session_updates = fake_supabase.updated_rows("sessions")
    assert any(update["values"].get("status") == "completed" for update in session_updates)
    recap_update = next(update for update in session_updates if "recap" in update["values"])
    # The stored recap carries the same new_cards payload as the response.
    assert recap_update["values"]["recap"]["new_cards"] == [
        {"type": "phrase", "front": "I am exhausted", "back": "estoy agotado"}
    ]
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

    response = await client.post("/sessions/end", json={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    assert fake_supabase.inserted_rows("cards") == []
    # Only the completion update plus the recap write happened; no card/profile updates.
    assert fake_supabase.updated_rows("cards") == []
    assert fake_supabase.updated_rows("profiles") == []
    assert fake_supabase.upserted_rows("user_languages") == []
    assert fake_supabase.inserted_rows("card_reviews") == []  # ungraded → no log row
    # `new_cards` is present (empty) in the stored recap even with no cards.
    recap_update = next(
        update for update in fake_supabase.updated_rows("sessions") if "recap" in update["values"]
    )
    assert recap_update["values"]["recap"]["new_cards"] == []


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

    response = await client.post("/sessions/end", json={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    assert fake_supabase.inserted_rows("card_reviews") == []
    assert fake_supabase.select_filters_rows("cards")[-1] == {
        "user_id": "user-1",
        "language": "fr",
    }
    assert fake_supabase.upserted_rows("user_languages") == [
        {"user_id": "user-1", "language": "fr", "level": "B2"}
    ]


@pytest.mark.asyncio
async def test_end_session_drops_candidates_matching_existing_cards(
    client, fake_supabase, monkeypatch
):
    """Backstop: a candidate whose front/back matches an existing card is never written."""
    result = PostSessionResult(
        new_cards=[
            # Punctuation/case variants of the user's existing card — must be dropped.
            CardCandidate(
                type="phrase",
                front="I am Exhausted!",
                back="estoy agotado",
                source_sentence="estoy muy agotado hoy",
                reason="(a): learner hesitated",
            ),
            # Genuinely new content — survives the backstop.
            CardCandidate(
                type="phrase",
                front="la cuenta",
                back="the bill",
                source_sentence="¿La cuenta, por favor?",
                reason="(c): tutor offered 'la cuenta' instead of improvised phrasing",
            ),
        ],
        reviewed_cards=[],
        recap=SessionRecap(positives=[], key_corrections=[], next_time_preview="next"),
        profile_updates=ProfileUpdates(),
    )

    async def fake_run(_prompt, deps=None):
        # The read-only recent-cards feed is front/back only, language-scoped.
        assert all(set(card) == {"front", "back"} for card in deps["existing_cards"])
        return type("R", (), {"output": result})()

    monkeypatch.setattr(voca_main.post_session_agent, "run", fake_run)
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "active", "language": "es"}
    ]
    fake_supabase.results[("transcripts", "select")] = []
    # The same rows feed both the due-card lookup and the recent-cards select;
    # front/back-only rows keep `existing_cards` compact like the real select.
    fake_supabase.results[("cards", "select")] = [
        {"front": "I am exhausted", "back": "estoy agotado"}
    ]

    response = await client.post("/sessions/end", json={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["new_cards_count"] == 1
    # Only the non-duplicating candidate reached the cards table.
    inserted_cards = fake_supabase.inserted_rows("cards")
    assert [card["front"] for card in inserted_cards] == ["la cuenta"]
    # The recap's new_cards payload keeps its exact shape, minus the dropped card.
    assert response.json()["recap"]["new_cards"] == [
        {"type": "phrase", "front": "la cuenta", "back": "the bill"}
    ]
    # The recent-cards select was scoped to the user and the session's language.
    assert fake_supabase.select_filters_rows("cards")[-1] == {
        "user_id": "user-1",
        "language": "es",
    }


@pytest.mark.asyncio
async def test_end_session_collapses_duplicate_candidates(client, fake_supabase, monkeypatch):
    """Repeated items yield one card, even when the model repeats itself."""
    result = PostSessionResult(
        new_cards=[
            CardCandidate(
                type="word",
                front="gato",
                back="cat",
                source_sentence="El gato duerme.",
                reason="(a): asked 'what does gato mean?'",
            ),
            CardCandidate(
                type="word",
                front="GATO",
                back="cat",
                source_sentence="el gato duerme",
                reason="(a): asked again later",
            ),
            CardCandidate(
                type="correction",
                front="un tacos",
                back="unos tacos",
                source_sentence="Quisiero un tacos de pastor.",
                reason="(b): tutor reformulated to 'unos tacos'",
            ),
        ],
        reviewed_cards=[],
        recap=SessionRecap(positives=[], key_corrections=[], next_time_preview="next"),
        profile_updates=ProfileUpdates(),
    )

    async def fake_run(_prompt, deps=None):
        return type("R", (), {"output": result})()

    monkeypatch.setattr(voca_main.post_session_agent, "run", fake_run)
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "active", "language": "es"}
    ]
    fake_supabase.results[("transcripts", "select")] = []
    fake_supabase.results[("cards", "select")] = []

    response = await client.post("/sessions/end", json={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["new_cards_count"] == 2
    inserted_cards = fake_supabase.inserted_rows("cards")
    assert [card["front"] for card in inserted_cards] == ["gato", "un tacos"]


# --- Deterministic card-harvest backstop -----------------------------------------


def test_harvest_new_cards_caps_at_five_cards():
    candidates = [
        CardCandidate(
            type="word",
            front=f"word-{index}",
            back=f"palabra-{index}",
            source_sentence="s",
            reason="(b): tutor correction",
        )
        for index in range(7)
    ]
    kept = voca_main.harvest_new_cards(candidates, [])
    assert len(kept) == 5
    assert [card.front for card in kept] == [f"word-{index}" for index in range(5)]


def test_harvest_new_cards_normalizes_before_matching():
    """Case and punctuation cannot smuggle a duplicate past the backstop."""
    existing = [{"front": "I am exhausted", "back": "¡Estoy agotado!"}]
    duplicate = CardCandidate(
        type="phrase",
        front="i am EXHAUSTED",
        back="estoy… agotado",
        source_sentence="s",
        reason="(a): asked for it",
    )
    fresh = CardCandidate(
        type="phrase",
        front="tener sed",
        back="to be thirsty",
        source_sentence="s",
        reason="(a): asked 'how do you say thirsty?'",
    )
    kept = voca_main.harvest_new_cards([duplicate, fresh], existing)
    assert [card.front for card in kept] == ["tener sed"]


# --- Lesson-aware session end: sweep excludes lesson-graded cards ------------------


def completed_lesson() -> dict:
    lesson = new_lesson(
        LessonSpec(template="role_play", title="At the café"),
        [],
        [{"id": "card-1", "front": "quisiera", "back": "I would like"}],
        "reason",
        "Intro",
    )
    lesson["status"] = "completed"
    lesson["completed_at"] = "2025-01-01T01:00:00+00:00"
    lesson["grades"] = [
        {"card_id": "card-1", "outcome": "pass", "bonus_use": True, "evidence": "lo usó"}
    ]
    lesson["summary"] = {
        "headline": "Ordered coffee confidently",
        "positives": ["good formality"],
        "key_phrases": ["¿me trae la cuenta?"],
        "bonus_uses": ["Quisiera un cortado, por favor."],
    }
    return lesson


@pytest.mark.asyncio
async def test_end_session_sweeps_only_ungraded_cards(client, fake_supabase, monkeypatch):
    """Cards already graded by a lesson never re-enter the analyst's grading slate."""
    fake_supabase.results[("sessions", "select")] = [
        {
            "id": "sess-1",
            "user_id": "user-1",
            "status": "active",
            "language": "es",
            "lessons": [completed_lesson()],
        }
    ]
    fake_supabase.results[("transcripts", "select")] = [
        {"speaker": "user", "text": "¿Cómo digo 'I am exhausted'?"}
    ]
    fake_supabase.results[("cards", "select")] = [
        {"id": "card-1", "front": "quisiera", "fsrs_data": new_card_state()},
        {"id": "card-2", "front": "exhausted", "fsrs_data": new_card_state()},
    ]
    result = PostSessionResult(
        new_cards=[],
        reviewed_cards=[CardGrade(card_id="card-2", outcome="recognition_pass")],
        recap=SessionRecap(positives=[], key_corrections=[], next_time_preview="next"),
        profile_updates=ProfileUpdates(),
    )

    async def fake_run(_prompt, deps=None):
        # The lesson-graded card is gone from the analyst's slate; the untouched
        # small-talk card is still due.
        assert deps["due_cards"] == [{"id": "card-2", "front": "exhausted", "back": ""}]
        # The analyst sees this session's lessons to inform the recap.
        assert deps["lessons"][0]["spec"]["title"] == "At the café"
        return type("R", (), {"output": result})()

    monkeypatch.setattr(voca_main.post_session_agent, "run", fake_run)
    response = await client.post("/sessions/end", json={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 200
    recap = response.json()["recap"]
    assert recap["lessons"][0]["title"] == "At the café"
    assert recap["lessons"][0]["template_name"] == "Role Play"
    assert recap["lessons"][0]["bonus_uses_count"] == 1
    assert recap["lessons"][0]["summary"]["headline"] == "Ordered coffee confidently"
    # The small-talk card's review has no lesson_id (the lesson already logged its own).
    review_rows = fake_supabase.inserted_rows("card_reviews")
    assert review_rows[0]["card_id"] == "card-2"
    assert review_rows[0].get("lesson_id") is None


@pytest.mark.asyncio
async def test_grade_and_complete_writes_fsrs_and_recap_payload(client, fake_supabase, monkeypatch):
    """The grader path: lesson-completed grades write FSRS + card_reviews.lesson_id."""
    lesson = new_lesson(
        LessonSpec(template="role_play", title="At the café"),
        [],
        [{"id": "card-1", "front": "quisiera", "back": "I would like"}],
        "reason",
        "Intro",
    )
    lesson["status"] = "active"
    lesson["accepted_at"] = "2025-01-01T00:00:10+00:00"
    fake_supabase.results[("sessions", "select")] = [active(lessons=[lesson])]
    fake_supabase.results[("transcripts", "select")] = [
        {
            "speaker": "user",
            "text": "Quisiera un cortado, por favor.",
            "created_at": "2025-01-01T00:00:20+00:00",
        }
    ]
    fake_supabase.results[("cards", "select")] = [
        {"id": "card-1", "front": "quisiera", "fsrs_data": new_card_state()}
    ]

    async def fake_run(_prompt, deps=None):
        assert deps["lesson"]["spec"]["title"] == "At the café"
        grades = LessonGrades(
            grades=[
                TargetGrade(card_id="card-1", outcome="pass", evidence="lo usó"),
                # A card the lesson never targeted — must be ignored.
                TargetGrade(card_id="card-9", outcome="miss", evidence="x"),
            ],
            summary=LessonSummary(headline="Great", positives=[], key_phrases=[]),
            bonus_uses=["Quisiera un cortado."],
        )
        return type("R", (), {"output": grades})()

    monkeypatch.setattr(voca_main.lesson_grader_agent, "run", fake_run)

    completed = await voca_main.grade_and_complete("user-1", "sess-1", "es")
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["summary"]["bonus_uses"] == ["Quisiera un cortado."]
    # Grades are stored as-is, but only a TARGETED card hit FSRS.
    review_rows = fake_supabase.inserted_rows("card_reviews")
    assert [row["card_id"] for row in review_rows] == ["card-1"]
    assert review_rows[0]["lesson_id"] == lesson["id"]
    assert review_rows[0]["rating"] == int(Rating.Good)
    stored = fake_supabase.updated_rows("sessions")[-1]["values"]["lessons"]
    assert stored[0]["status"] == "completed"
    assert len(stored[0]["grades"]) == 2  # non-target grade kept for the record only


# --- translate + harvest backstops -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_session_rejects_already_ended_without_rerunning_agents(
    client, fake_supabase, monkeypatch
):
    """A completed session cannot be ended twice; the analyst must never run again."""
    calls = 0

    async def fail_run(_prompt, deps=None):
        nonlocal calls
        calls += 1
        raise AssertionError("post-session agent ran on an already-ended session")

    monkeypatch.setattr(voca_main.post_session_agent, "run", fail_run)
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "completed"}
    ]
    response = await client.post("/sessions/end", json={"session_id": "sess-1"}, headers=AUTH)
    assert response.status_code == 409
    assert calls == 0
    # No transcript fetch or card writes happened either.
    assert fake_supabase.select_filters_rows("transcripts") == []
    assert fake_supabase.inserted_rows("cards") == []


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
