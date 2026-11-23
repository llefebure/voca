-- Canvas chat: one continuous conversation per session. Nothing legacy is
-- kept: `sessions.plan` (single upfront plan) is dropped; panels are transient
-- exhibits whose state replays from transcript payload rows, so no session
-- column stores them.

ALTER TABLE sessions DROP COLUMN plan;

-- Structured chat events (panel_shown / panel_hidden) are persisted so
-- continue-session can replay them; plain chat rows keep payload NULL.
ALTER TABLE transcripts ADD COLUMN payload JSONB;
