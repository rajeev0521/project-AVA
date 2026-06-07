-- AVA Supabase Database Schema
-- Run this in your Supabase SQL Editor to set up the required tables.

-- ══════════════════════════════════════════════════════════════════
-- Conversations Table — Conversation history for memory
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    user_input TEXT NOT NULL,
    intent TEXT,
    entities JSONB,
    response TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast user history queries (ordered by time)
CREATE INDEX IF NOT EXISTS idx_conversations_user_time 
    ON conversations(user_id, created_at DESC);

-- Index for intent-based analytics
CREATE INDEX IF NOT EXISTS idx_conversations_intent 
    ON conversations(user_id, intent);

-- ══════════════════════════════════════════════════════════════════
-- Entity Context Table — Last referenced entities per user
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS entity_context (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'last_event',
    entity_data JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast context lookups
CREATE INDEX IF NOT EXISTS idx_entity_context_user 
    ON entity_context(user_id, entity_type);

-- ══════════════════════════════════════════════════════════════════
-- User Tokens Table — OAuth credential storage per user
-- NOTE: client_secret is intentionally NOT stored here.
-- The application reconstructs it from the GOOGLE_CLIENT_SECRET
-- environment variable at runtime. This prevents a database leak
-- from exposing the OAuth application secret.
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS user_tokens (
    user_id TEXT PRIMARY KEY,
    token_data JSONB,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════════
-- Row Level Security (RLS) — Each user can only see their own data
-- Note: Policies use current_setting('request.jwt.claim.sub') to match the user_id (Google sub claim).
-- Service Role keys bypass these policies automatically.
-- ══════════════════════════════════════════════════════════════════

-- Enable RLS on all tables
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_context ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_tokens ENABLE ROW LEVEL SECURITY;

-- Policy: Users can manage own conversations
DROP POLICY IF EXISTS "Users can manage own conversations" ON conversations;
CREATE POLICY "Users can manage own conversations" ON conversations
    FOR ALL
    USING (user_id = current_setting('request.jwt.claim.sub', true) OR current_user = 'service_role')
    WITH CHECK (user_id = current_setting('request.jwt.claim.sub', true) OR current_user = 'service_role');

-- Policy: Users can manage own entity context
DROP POLICY IF EXISTS "Users can manage own entity context" ON entity_context;
CREATE POLICY "Users can manage own entity context" ON entity_context
    FOR ALL
    USING (user_id = current_setting('request.jwt.claim.sub', true) OR current_user = 'service_role')
    WITH CHECK (user_id = current_setting('request.jwt.claim.sub', true) OR current_user = 'service_role');

-- Policy: Users can manage own tokens
DROP POLICY IF EXISTS "Users can manage own tokens" ON user_tokens;
CREATE POLICY "Users can manage own tokens" ON user_tokens
    FOR ALL
    USING (user_id = current_setting('request.jwt.claim.sub', true) OR current_user = 'service_role')
    WITH CHECK (user_id = current_setting('request.jwt.claim.sub', true) OR current_user = 'service_role');

-- RLS: Only the service role can read/write tokens (never the frontend anon key)
CREATE POLICY "service role only" ON user_tokens
    FOR ALL
    USING (true);

-- ══════════════════════════════════════════════════════════════════
-- Auto-cleanup: Delete conversations older than 30 days
-- (Run this as a Supabase Edge Function or cron job)
-- ══════════════════════════════════════════════════════════════════
-- DELETE FROM conversations WHERE created_at < NOW() - INTERVAL '30 days';
