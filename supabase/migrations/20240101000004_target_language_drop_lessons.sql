-- Target (learning) language per profile. The interface stays English; only
-- the language the user is learning becomes configurable. Spanish is the only
-- supported value today; future languages add entries here and in the backend
-- `languages` service.
ALTER TABLE profiles ADD COLUMN target_language TEXT NOT NULL DEFAULT 'es';

-- Lessons were never a real bank: they are instantiated on the fly from
-- structural templates by the session planner and stored in `sessions.plan`.
-- The unused `lessons` table goes away.
DROP TABLE lessons;
