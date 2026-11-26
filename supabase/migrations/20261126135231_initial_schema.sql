-- Voca's squashed baseline: the whole schema in one migration.
-- Recreated 2026-11-26 after the 10-migration pre-deploy history collapsed
-- into this single clean baseline (nothing was deployed; every local/worktree
-- stack database resets and replays just this file).
--
-- Filename note: created by `uv run task migration:new` in the CLI-canonical
-- `YYYYMMDDHHMMSS_<name>.sql` format. Do NOT hand-type or "prettify"
-- migration filenames — the CLI keys migrations by the leading digit-run of
-- the filename, so underscore-dated names degenerate to a shared version and
-- the second migration of a day fails to apply.

-- It hardens the schema beyond what the migration history accumulated:
--
-- * a `language_code` domain — the single canonical place the supported
--   target-language list lives; every language-typed column uses it, and a
--   drift-guard test keeps both apps' language maps in sync with it,
-- * NOT NULLs and CHECKs on every enum-ish column (status, speaker, card
--   type, FSRS rating, fsrs_data shape),
-- * ON DELETE CASCADE from auth.users down through every owned row (account
--   deletion used to be blocked by a bare profiles FK), and
-- * RLS rewritten: every policy targets `authenticated`, USING/WITH CHECK
--   pairs, and dead INSERT policies removed — table writes happen only where
--   the browser really writes (see the per-table policy notes).

-- ============================================================================
-- Language governance
-- ============================================================================

-- The supported target-language list lives EXACTLY here: all five language
-- columns (profiles.target_language, sessions.language, cards.language,
-- user_languages.language, card_reviews.language) use this domain, so the DB
-- and the app maps (`src/voca/services/languages.py`,
-- `frontend/lib/languages.ts`) cannot disagree — drift-guard tests in both
-- suites parse this line and fail loudly on divergence.
--
-- Adding a language later is one migration:
--   ALTER DOMAIN public.language_code DROP CONSTRAINT language_code_check;
--   ALTER DOMAIN public.language_code ADD CHECK (VALUE IN ('es', 'fr', ...));
-- plus entries in both apps' language maps (and its TTS/model config).
CREATE DOMAIN public.language_code AS TEXT CHECK (VALUE IN ('es'));

-- ============================================================================
-- Tables
-- ============================================================================

-- Identity + pointers only: the target-language pointer (what the user lands
-- on) and the onboarding stamp (NULL = wizard not finished; the chat page
-- gates on it). Learner context (level/goals/interests) is per-language and
-- lives solely in user_languages below; profiles' legacy goals/level/
-- interests copies are gone with the never-deployed pre-multi-language data.
-- Rows are created automatically by the on_auth_user_created trigger below —
-- the browser never inserts here, and auth.users deletion cascades.
CREATE TABLE public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    target_language public.language_code NOT NULL DEFAULT 'es',
    onboarded_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE public.sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed')),
    start_time TIMESTAMPTZ DEFAULT now(),
    end_time TIMESTAMPTZ,
    language public.language_code NOT NULL DEFAULT 'es',
    recap JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per chat turn (speaker user|tutor) and per structured UI event
-- (speaker 'system', text '', payload carrying the event kind/data — panel
-- state replays from these payload rows). Written by the backend only.
CREATE TABLE public.transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES public.sessions(id) ON DELETE CASCADE,
    speaker TEXT NOT NULL CHECK (speaker IN ('user', 'tutor', 'system')),
    text TEXT NOT NULL,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- FSRS review cards. fsrs_data holds the current card state only (fsrs v6
-- keeps no counters); graded history lives in card_reviews. Written by the
-- backend only (the analyst harvest).
CREATE TABLE public.cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('word', 'phrase', 'correction', 'grammar')),
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    source_sentence TEXT,
    fsrs_data JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(fsrs_data) = 'object'),
    last_review TIMESTAMPTZ,
    next_review TIMESTAMPTZ,
    language public.language_code NOT NULL DEFAULT 'es',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Append-only FSRS review log (one row per graded review, written by
-- /sessions/end); language is denormalized so progress metrics filter without
-- a join. session_id is nullable: ON DELETE SET NULL keeps the log intact
-- when a session is removed.
CREATE TABLE public.card_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES public.cards(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    language public.language_code NOT NULL,
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 4), -- FSRS: 1=Again 2=Hard 3=Good 4=Easy
    reviewed_at TIMESTAMPTZ NOT NULL,
    session_id UUID REFERENCES public.sessions(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-language learner context (a CEFR level is a level *in* a language;
-- goals name the language; last_practiced_at drives the practiced-languages
-- ordering). One row per (user, language) — the one table the browser still
-- writes (onboarding wizard, profile edits; via upsert).
CREATE TABLE public.user_languages (
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    language public.language_code NOT NULL,
    level TEXT,
    goals TEXT,
    interests TEXT,
    last_practiced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, language)
);

-- ============================================================================
-- Indexes — the app's query shapes (Postgres does not index FK columns
-- automatically; nothing else is indexed)
-- ============================================================================

-- Session history per user; language-scoped listing/switching.
CREATE INDEX idx_sessions_user_id ON public.sessions(user_id);
CREATE INDEX idx_sessions_user_language ON public.sessions(user_id, language);

-- Every transcript read orders by created_at within one session.
CREATE INDEX idx_transcripts_session_created ON public.transcripts(session_id, created_at);

-- SRS due queue (user+language+next_review) and card library ordering.
CREATE INDEX idx_cards_user_language_due ON public.cards(user_id, language, next_review);
CREATE INDEX idx_cards_user_created_at ON public.cards(user_id, created_at);

-- Progress metrics always filter by user AND language; recaps look up a
-- session's graded reviews; FSRS updates resolve a card's log.
CREATE INDEX idx_card_reviews_user_language_at ON public.card_reviews(user_id, language, reviewed_at);
CREATE INDEX idx_card_reviews_session_id ON public.card_reviews(session_id);
CREATE INDEX idx_card_reviews_card_id ON public.card_reviews(card_id);

-- ============================================================================
-- Row Level Security — every policy targets `authenticated` with an
-- auth.uid() match; the service-role key (backend) bypasses RLS entirely.
-- ============================================================================

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transcripts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.card_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_languages ENABLE ROW LEVEL SECURITY;

-- No INSERT policy: profiles rows are created by the on_auth_user_created
-- trigger; no DELETE policy: auth.users deletion cascades.
CREATE POLICY "profiles_select_own" ON public.profiles
    FOR SELECT TO authenticated
    USING ((SELECT auth.uid()) = id);

CREATE POLICY "profiles_update_own" ON public.profiles
    FOR UPDATE TO authenticated
    USING ((SELECT auth.uid()) = id)
    WITH CHECK ((SELECT auth.uid()) = id);

-- No INSERT policy: sessions are created by the backend only (service role).
CREATE POLICY "sessions_select_own" ON public.sessions
    FOR SELECT TO authenticated
    USING ((SELECT auth.uid()) = user_id);

CREATE POLICY "sessions_update_own" ON public.sessions
    FOR UPDATE TO authenticated
    USING ((SELECT auth.uid()) = user_id)
    WITH CHECK ((SELECT auth.uid()) = user_id);

-- No INSERT policy: transcripts are backend-written, so browser clients can
-- never fabricate speaker='tutor' rows.
CREATE POLICY "transcripts_select_own" ON public.transcripts
    FOR SELECT TO authenticated
    USING (
        EXISTS (
            SELECT 1
            FROM public.sessions
            WHERE
                sessions.id = transcripts.session_id
                AND sessions.user_id = (SELECT auth.uid())
        )
    );

-- The Library page deletes cards from the browser; the analyst harvest inserts.
CREATE POLICY "cards_select_own" ON public.cards
    FOR SELECT TO authenticated
    USING ((SELECT auth.uid()) = user_id);

CREATE POLICY "cards_update_own" ON public.cards
    FOR UPDATE TO authenticated
    USING ((SELECT auth.uid()) = user_id)
    WITH CHECK ((SELECT auth.uid()) = user_id);

CREATE POLICY "cards_delete_own" ON public.cards
    FOR DELETE TO authenticated
    USING ((SELECT auth.uid()) = user_id);

-- No INSERT policy: review rows are appended by the backend only (append-only
-- log; users see them but never write).
CREATE POLICY "card_reviews_select_own" ON public.card_reviews
    FOR SELECT TO authenticated
    USING ((SELECT auth.uid()) = user_id);

-- The one table the browser still inserts to (onboarding/profile rows).
CREATE POLICY "user_languages_select_own" ON public.user_languages
    FOR SELECT TO authenticated
    USING ((SELECT auth.uid()) = user_id);

CREATE POLICY "user_languages_insert_own" ON public.user_languages
    FOR INSERT TO authenticated
    WITH CHECK ((SELECT auth.uid()) = user_id);

CREATE POLICY "user_languages_update_own" ON public.user_languages
    FOR UPDATE TO authenticated
    USING ((SELECT auth.uid()) = user_id)
    WITH CHECK ((SELECT auth.uid()) = user_id);

-- ============================================================================
-- Profile auto-creation
-- ============================================================================

-- Every new auth user gets a profiles row immediately, so /sessions/start and
-- friends never hit an FK violation for a missing profile (the browser
-- doesn't create it). SECURITY DEFINER (it inserts into public as the
-- auth-schema trigger owner); fully qualified names plus the empty
-- search_path keep it schema-sniff-proof, and EXECUTE is revoked from web
-- roles.
CREATE FUNCTION public.handle_new_user() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = ''
    AS $$
BEGIN
    INSERT INTO public.profiles (id) VALUES (new.id);
    RETURN new;
END;
$$;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_new_user();

REVOKE EXECUTE ON FUNCTION public.handle_new_user() FROM anon, authenticated, public;

-- ============================================================================
-- Touches
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS moddatetime WITH SCHEMA extensions;

CREATE TRIGGER profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW
    EXECUTE FUNCTION extensions.moddatetime(updated_at);
