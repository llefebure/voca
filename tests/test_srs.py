"""FSRS scheduling wrapper tests (`voca.services.srs`)."""

import json
from datetime import UTC, datetime

from fsrs import Rating

from voca.services.srs import (
    VOCA_RATING_MAP,
    new_card_state,
    next_review,
    review_card_state,
)


def test_new_card_state_is_fsrs_json():
    state = json.loads(new_card_state())
    assert isinstance(state, dict)
    assert "due" in state
    # A brand-new card is due immediately (within a few seconds of creation).
    due = next_review(new_card_state())
    assert abs((datetime.now(UTC) - due).total_seconds()) < 60


def test_voca_rating_map_covers_all_outcomes():
    assert set(VOCA_RATING_MAP) == {"strong_pass", "pass", "recognition_pass", "miss"}
    assert VOCA_RATING_MAP["miss"] == Rating.Again
    assert VOCA_RATING_MAP["pass"] == Rating.Good
    assert VOCA_RATING_MAP["strong_pass"] == Rating.Easy
    assert VOCA_RATING_MAP["recognition_pass"] == Rating.Easy


def test_review_card_state_returns_the_log():
    """The log exposes the FSRS rating as an int plus the review timestamp."""
    state = new_card_state()
    review_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    new_state, review_log = review_card_state(state, Rating.Good, review_time)

    assert review_log["rating"] == 3  # FSRS: 1=Again 2=Hard 3=Good 4=Easy
    assert review_log["reviewed_at"] == review_time.isoformat()
    # The returned state is the same as the state-only helper produces.
    assert json.loads(new_state)["last_review"] == review_time.isoformat()
