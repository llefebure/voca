-- Lesson loop: sessions hold a conversation state machine (small talk ⇄ lessons).
-- Nothing legacy is kept: `sessions.plan` (single upfront plan) is dropped; the
-- `lessons` JSONB array is the single lesson store.

ALTER TABLE sessions ADD COLUMN lessons JSONB NOT NULL DEFAULT '[]';
ALTER TABLE sessions DROP COLUMN plan;

-- Structured chat events (proposal cards, material blocks, summaries) are
-- persisted so continue-session can replay them; plain chat rows keep payload NULL.
ALTER TABLE transcripts ADD COLUMN payload JSONB;

-- Grades the per-lesson grader produced (the session-end sweep only grades
-- cards no lesson covered).
ALTER TABLE card_reviews ADD COLUMN lesson_id TEXT;
