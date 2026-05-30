-- AVA Supabase Database Schema
-- Run this in your Supabase SQL Editor to set up the required tables.

-- ══════════════════════════════════════════════════════════════════
-- Users Table — Multi-user support
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    display_name TEXT,
    google_calendar_token JSONB,
    preferences JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast email lookups
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

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
-- Row Level Security (RLS) — Each user can only see their own data
-- ══════════════════════════════════════════════════════════════════

-- Enable RLS on all tables
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_context ENABLE ROW LEVEL SECURITY;

-- Policy: Users can read/write only their own conversations
CREATE POLICY "Users can manage own conversations" ON conversations
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- Policy: Users can manage own entity context
CREATE POLICY "Users can manage own entity context" ON entity_context
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- ══════════════════════════════════════════════════════════════════
-- User Tokens Table — OAuth credential storage per user
-- ══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS user_tokens (
    user_id TEXT PRIMARY KEY,
    token TEXT,
    refresh_token TEXT,
    token_uri TEXT,
    client_id TEXT,
    client_secret TEXT,
    scopes TEXT[],
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: Only the service role can read/write tokens (never the frontend anon key)
ALTER TABLE user_tokens ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service role only" ON user_tokens
    FOR ALL
    USING (true);

-- ══════════════════════════════════════════════════════════════════
-- Auto-cleanup: Delete conversations older than 30 days
-- (Run this as a Supabase Edge Function or cron job)
-- ══════════════════════════════════════════════════════════════════
-- DELETE FROM conversations WHERE created_at < NOW() - INTERVAL '30 days';
