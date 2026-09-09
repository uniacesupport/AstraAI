-- AstraAI PostgreSQL schema
-- Compatible with Neon PostgreSQL
-- Corrected: current_role renamed to user_role

CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,

    user_role VARCHAR(50)
        NOT NULL DEFAULT 'assistant',

    personality VARCHAR(50)
        NOT NULL DEFAULT 'default',

    language VARCHAR(10)
        NOT NULL DEFAULT 'en',

    mode VARCHAR(50)
        NOT NULL DEFAULT 'general',

    created_at TIMESTAMP
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMP
        NOT NULL DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS conversations (
    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    role VARCHAR(20) NOT NULL,

    content TEXT NOT NULL,

    created_at TIMESTAMP
        NOT NULL DEFAULT NOW()
);


CREATE INDEX IF NOT EXISTS idx_conversations_user_time
    ON conversations(user_id, created_at DESC);


CREATE TABLE IF NOT EXISTS memories (
    id BIGSERIAL PRIMARY KEY,

    user_id BIGINT NOT NULL
        REFERENCES users(user_id)
        ON DELETE CASCADE,

    memory_key VARCHAR(100) NOT NULL,

    memory_value TEXT NOT NULL,

    importance INTEGER
        NOT NULL DEFAULT 1,

    created_at TIMESTAMP
        NOT NULL DEFAULT NOW(),

    updated_at TIMESTAMP
        NOT NULL DEFAULT NOW(),

    UNIQUE(user_id, memory_key)
);


CREATE INDEX IF NOT EXISTS idx_memories_user
    ON memories(user_id);
