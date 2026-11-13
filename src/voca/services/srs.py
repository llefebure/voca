"""Spaced-repetition scheduling on top of the `fsrs` package.

Card state is stored per row as a JSON object in `cards.fsrs_data`;
`next_review` is its materialized due date.
"""

import json
from datetime import UTC, datetime
from typing import Any

from fsrs import Card, Rating, Scheduler

# Map Voca's inferred outcomes to FSRS ratings:
# - strong_pass: effortless, correct recall -> Easy
# - pass: recall (possibly with effort) -> Good
# - recognition_pass: could understand it, not produce it -> Easy
# - miss: forgot or wrong -> Again
VOCA_RATING_MAP = {
    "strong_pass": Rating.Easy,
    "pass": Rating.Good,
    "recognition_pass": Rating.Easy,
    "miss": Rating.Again,
}


def new_card_state() -> str:
    """Initial FSRS card state as a JSON string (an object with a `due` key)."""
    return json.dumps(Card().to_dict())


def review_card_state(
    state_json: str, rating: Rating, when: datetime | None = None
) -> tuple[str, dict[str, Any]]:
    """Apply a review rating to a card; return the updated FSRS state JSON and log.

    The log carries the FSRS rating as an int (1=Again 2=Hard 3=Good 4=Easy) and
    the review timestamp, ready for a `card_reviews` row.
    """
    card = Card.from_dict(json.loads(state_json))
    at = when or datetime.now(UTC)
    updated_card, review_log = Scheduler().review_card(card, rating, at)
    return (
        json.dumps(updated_card.to_dict()),
        {"rating": int(rating), "reviewed_at": review_log.review_datetime.isoformat()},
    )


def update_card_state(state_json: str, rating: Rating, when: datetime | None = None) -> str:
    """Apply a review rating to a card and return the updated FSRS state JSON."""
    return review_card_state(state_json, rating, when)[0]


def next_review(state_json: str) -> datetime:
    """The due date of the card with this FSRS state."""
    return Card.from_dict(json.loads(state_json)).due
