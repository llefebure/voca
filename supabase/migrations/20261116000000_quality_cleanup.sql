-- Quality cleanup: RLS delete policy for cards, FK-adjacent indexes, dead columns.
-- Single linear migration; applies at the next `supabase migration up`.

-- Bug fix: the Library page deletes cards from the browser (anon key via
-- PostgREST, frontend/app/library/page.tsx:74). Only SELECT/INSERT/UPDATE
-- policies existed (20261109000000), so deletes affected 0 rows silently and
-- the card reappeared on the next load.
CREATE POLICY "Users can delete their own cards" ON cards FOR DELETE USING (auth.uid() = user_id);

-- Cleanup: dead columns (verified write-only — nothing in src/ or frontend/ reads them).
-- Added by 20261109000001, referenced by zero code anywhere.
ALTER TABLE sessions DROP COLUMN current_phase;
-- Written ("new") by /sessions/end, never read; the real schedule lives in fsrs_data.
ALTER TABLE cards DROP COLUMN state;
-- The only writer was the onboarding wizard's Tuning step, which is being removed.
ALTER TABLE profiles DROP COLUMN preferences;

-- Cleanup: indexes. Postgres does not index FK columns automatically; these
-- back the app's actual queries (session history per user, transcripts by
-- session, SRS due queue, progress metrics over card_reviews).
CREATE INDEX idx_sessions_user_id ON sessions(user_id);
CREATE INDEX idx_sessions_user_language ON sessions(user_id, language);
CREATE INDEX idx_transcripts_session_id ON transcripts(session_id);
CREATE INDEX idx_cards_user_language_due ON cards(user_id, language, next_review);
CREATE INDEX idx_cards_user_created_at ON cards(user_id, created_at);
CREATE INDEX idx_card_reviews_user_at ON card_reviews(user_id, reviewed_at);
CREATE INDEX idx_card_reviews_session_id ON card_reviews(session_id);
