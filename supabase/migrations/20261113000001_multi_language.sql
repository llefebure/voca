-- Multi-language practice. Sessions and cards get stamped with the language
-- they belong to at creation time (backfilled to 'es' — all prior data was
-- single-language), and per-language learner context moves into a new
-- `user_languages` table. `profiles.target_language` becomes the *active*
-- language pointer: the language being practiced right now.

ALTER TABLE sessions ADD COLUMN language TEXT NOT NULL DEFAULT 'es';
ALTER TABLE cards ADD COLUMN language TEXT NOT NULL DEFAULT 'es';

CREATE TABLE user_languages (
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    level TEXT,
    goals TEXT,
    interests TEXT,
    last_practiced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, language)
);

ALTER TABLE user_languages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own languages" ON user_languages FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY "Users can update their own languages" ON user_languages FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "Users can insert their own languages" ON user_languages FOR INSERT WITH CHECK (auth.uid() = user_id);
