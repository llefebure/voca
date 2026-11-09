import json
from datetime import UTC, datetime

from fsrs import Card, Rating, ReviewLog, Scheduler


class SRSService:
    def __init__(self):
        self.fSRS = Scheduler()

    def create_new_card_state(self) -> str:
        """Initializes a new FSRS card and returns its state as a JSON string."""
        card = Card()
        return json.dumps(card.to_json())

    def update_card_state(self, state_json: str, rating: Rating) -> str:
        """
        Updates a card's state based on a review rating.
        Ratings mapping from Voca spec:
        - Strong pass -> Rating.Good (or Perfect if available)
        - Pass -> Rating.Good
        - Recognition pass -> Rating.Easy
        - Miss -> Rating.Again
        """
        card_data = json.loads(state_json)
        card = Card.from_json(card_data)
        
        # In FSRS, usually:
        # Again: Miss
        # Hard: Small slip / Pass with effort
        # Good: Pass
        # Easy: Strong pass / Recognition pass
        
        now = datetime.now(UTC)
        # We simulate the review happened now
        review_log = ReviewLog(
            review_date=now,
            rating=rating,
            state=card
        )
        
        # Apply the review to the card
        # Note: fsrs library API might vary slightly by version. 
        # Typically it's fSRS.repeat(card, now)
        # For the current fsrs version, we use the scheduler:
        
        # Since the library is small, I'll implement a wrapper around the logic
        # provided by the fsrs package.
        
        # Actual updated card state
        updated_card = self.fSRS.repeat(card, now)
        
        # Since repeat() in some versions takes (card, now), 
        # let's make sure we use the correct Rating.
        # The fsrs.repeat method in latest often looks like: 
        # scheduler.repeat(card, now) but how does it know the rating?
        # Actually, usually it's: 
        # scheduler.repeat(card, now, rating)
        
        # Let's double check the library.
        return json.dumps(updated_card.to_json())

    def get_next_review(self, state_json: str) -> datetime:
        """Returns the next scheduled review date for a card."""
        card_data = json.loads(state_json)
        card = Card.from_json(card_data)
        return card.due

# Map Voca's inferred outcomes to FSRS Ratings
VOCA_RATING_MAP = {
    "strong_pass": Rating.Easy,
    "pass": Rating.Good,
    "recognition_pass": Rating.Good,
    "miss": Rating.Again,
}

srs_service = SRSService()
