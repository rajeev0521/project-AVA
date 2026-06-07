-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create long_term_memories table
CREATE TABLE IF NOT EXISTS long_term_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),
    embedding_model TEXT DEFAULT 'text-embedding-004',
    source TEXT NOT NULL CHECK (source = 'user_explicit') DEFAULT 'user_explicit',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_user_key UNIQUE (user_id, key)
);

-- Row Level Security
ALTER TABLE long_term_memories ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage own long term memories" ON long_term_memories
    FOR ALL
    USING (user_id = current_setting('request.jwt.claim.sub', true) OR current_user = 'service_role')
    WITH CHECK (user_id = current_setting('request.jwt.claim.sub', true) OR current_user = 'service_role');

CREATE POLICY "service role only ltm" ON long_term_memories
    FOR ALL
    USING (true);

-- Function for similarity search
CREATE OR REPLACE FUNCTION match_memories (
    query_embedding vector(768),
    query_user_id TEXT,
    match_threshold FLOAT DEFAULT 0.75,
    match_count INT DEFAULT 3
)
RETURNS TABLE (
    id UUID,
    key TEXT,
    content TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        long_term_memories.id,
        long_term_memories.key,
        long_term_memories.content,
        1 - (long_term_memories.embedding <=> query_embedding) AS similarity
    FROM long_term_memories
    WHERE long_term_memories.user_id = query_user_id
    AND 1 - (long_term_memories.embedding <=> query_embedding) >= match_threshold
    ORDER BY long_term_memories.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
