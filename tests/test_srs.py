"""FSRS scheduling wrapper tests (`voca.services.srs`)."""

import json
from datetime import UTC, datetime, timedelta

from fsrs import Rating

from voca.services.srs import VOCA_RATING_MAP, new_card_state, next_review, update_card_state


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


def test_update_card_state_uses_the_rating():
    state = new_card_state()
    again = update_card_state(state, Rating.Again)
    easy = update_card_state(state, Rating.Easy)

    # The rating must move the due date: a miss is rescheduled much sooner.
    assert next_review(again) < next_review(easy)
    # And a miss after a pass still lands sooner than the pass schedule.
    passed = update_card_state(again, Rating.Good)
    missed_again = update_card_state(passed, Rating.Again)
    assert next_review(missed_again) < next_review(passed)


def test_update_card_state_schedules_days_ahead_on_pass():
    state = new_card_state()
    updated = update_card_state(state, Rating.Good)
    # A first successful review moves the due date into the future.
    assert next_review(updated) > datetime.now(UTC)
    # And a second pass schedules even further out.
    twice = update_card_state(updated, Rating.Good)
    assert next_review(twice) > next_review(updated)


def test_update_card_state_accepts_explicit_review_time():
    state = new_card_state()
    review_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    updated = update_card_state(state, Rating.Good, review_time)
    due = next_review(updated)
    assert due.tzinfo is not None
    # Not rescheduled relative to "now", but to the explicit review time.
    assert due < datetime.now(UTC) + timedelta(days=1)
    assert due >= review_time
