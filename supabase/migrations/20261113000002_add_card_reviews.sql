-- Review log for FSRS-graded cards. The `cards.fsrs_data` JSONB snapshot holds
-- only the current card state (no review counters in fsrs v6), so "positive
-- recalls" and review activity over time can only come from an append-only
-- log. One row per graded review, written by `/sessions/end`; `language` is
-- denormalized from the card's session so progress metrics filter without a join.
CREATE TABLE card_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    rating INT NOT NULL, -- FSRS rating: 1=Again 2=Hard 3=Good 4=Easy
    reviewed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE card_reviews ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own card reviews" ON card_reviews FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can insert their own card reviews" ON card_reviews FOR INSERT WITH CHECK (auth.uid() = user_id);
