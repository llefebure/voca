-- Remember which session graded each review, so recaps can show per-card
-- outcomes against that session's planned targets. Nullable: logged rows from
-- before this column existed have no session attribution.
ALTER TABLE card_reviews
    ADD COLUMN session_id UUID REFERENCES sessions(id) ON DELETE SET NULL;
