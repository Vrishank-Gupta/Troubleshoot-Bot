-- ============================================================
-- Products
-- ============================================================
CREATE TABLE IF NOT EXISTS products (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    category    TEXT,
    aliases     TEXT[] DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_products_name ON products USING GIN (to_tsvector('english', name));

-- ============================================================
-- Issues
-- ============================================================
CREATE TABLE IF NOT EXISTS issues (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id       UUID REFERENCES products(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    category         TEXT,
    symptom_phrases  TEXT[] DEFAULT '{}',
    negative_phrases TEXT[] DEFAULT '{}',
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_issues_product_id ON issues(product_id);
CREATE INDEX IF NOT EXISTS idx_issues_symptoms ON issues USING GIN (symptom_phrases);

-- ============================================================
-- SOP Flows
-- ============================================================
CREATE TABLE IF NOT EXISTS sop_flows (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    product_id  UUID REFERENCES products(id) ON DELETE SET NULL,
    issue_id    UUID REFERENCES issues(id) ON DELETE SET NULL,
    sop_slug    TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    version     INT DEFAULT 1,
    status      TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'reviewed', 'published', 'archived')),
    flow_json   JSONB NOT NULL,
    source_file TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sop_flows_status ON sop_flows(status);
CREATE INDEX IF NOT EXISTS idx_sop_flows_product_id ON sop_flows(product_id);
CREATE INDEX IF NOT EXISTS idx_sop_flows_issue_id ON sop_flows(issue_id);
CREATE INDEX IF NOT EXISTS idx_sop_flows_slug ON sop_flows(sop_slug);
CREATE INDEX IF NOT EXISTS idx_sop_flows_created_at ON sop_flows(created_at DESC);

-- ============================================================
-- SOP Chunks  (for vector search)
-- ============================================================
CREATE TABLE IF NOT EXISTS sop_chunks (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sop_flow_id  UUID REFERENCES sop_flows(id) ON DELETE CASCADE,
    product_id   UUID REFERENCES products(id) ON DELETE CASCADE,
    issue_id     UUID REFERENCES issues(id) ON DELETE CASCADE,
    chunk_text   TEXT NOT NULL,
    chunk_type   TEXT,  -- title | symptom | step | prerequisite | escalation
    embedding    vector(1536),
    keywords     TEXT[] DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sop_chunks_sop_flow_id ON sop_chunks(sop_flow_id);
CREATE INDEX IF NOT EXISTS idx_sop_chunks_product_id ON sop_chunks(product_id);
CREATE INDEX IF NOT EXISTS idx_sop_chunks_embedding ON sop_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ============================================================
-- Conversations
-- ============================================================
CREATE TABLE IF NOT EXISTS conversations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    customer_id     TEXT NOT NULL,
    channel         TEXT DEFAULT 'web',
    product_id      UUID REFERENCES products(id) ON DELETE SET NULL,
    issue_id        UUID REFERENCES issues(id) ON DELETE SET NULL,
    sop_flow_id     UUID REFERENCES sop_flows(id) ON DELETE SET NULL,
    current_step_id TEXT,
    status          TEXT DEFAULT 'NEW' CHECK (status IN (
                        'NEW','AWAITING_PRODUCT','AWAITING_ISSUE',
                        'CLARIFYING','SOP_SELECTED','RUNNING_STEP',
                        'WAITING_STEP_RESPONSE','RESOLVED','ESCALATED','ABANDONED'
                    )),
    state_json      JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_customer_id ON conversations(customer_id);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_sop_flow_id ON conversations(sop_flow_id);

-- ============================================================
-- Conversation Events
-- ============================================================
CREATE TABLE IF NOT EXISTS conversation_events (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id    UUID REFERENCES conversations(id) ON DELETE CASCADE,
    event_type         TEXT NOT NULL,  -- user_message | bot_message | state_change | step_start | step_complete | escalation
    user_message       TEXT,
    bot_message        TEXT,
    detected_product   TEXT,
    detected_issue     TEXT,
    confidence_score   NUMERIC(5,4),
    current_step_id    TEXT,
    extra_data         JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_events_conversation_id ON conversation_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conv_events_event_type ON conversation_events(event_type);
CREATE INDEX IF NOT EXISTS idx_conv_events_created_at ON conversation_events(created_at DESC);

-- ============================================================
-- Escalations
-- ============================================================
CREATE TABLE IF NOT EXISTS escalations (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id       UUID REFERENCES conversations(id) ON DELETE SET NULL,
    customer_id           TEXT NOT NULL,
    product_name          TEXT,
    issue_name            TEXT,
    sop_title             TEXT,
    last_completed_step   TEXT,
    failed_step           TEXT,
    summary               TEXT,
    full_transcript       JSONB DEFAULT '[]',
    recommended_action    TEXT,
    status                TEXT DEFAULT 'open' CHECK (status IN ('open','assigned','resolved','closed')),
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_escalations_conversation_id ON escalations(conversation_id);
CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status);
CREATE INDEX IF NOT EXISTS idx_escalations_created_at ON escalations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_escalations_customer_id ON escalations(customer_id);

-- ============================================================
-- Analytics Events  (append-only event log)
-- ============================================================
CREATE TABLE IF NOT EXISTS analytics_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID,
    event_name      TEXT NOT NULL,
    product_name    TEXT,
    issue_name      TEXT,
    sop_slug        TEXT,
    step_id         TEXT,
    confidence      NUMERIC(5,4),
    extra_data      JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_event_name ON analytics_events(event_name);
CREATE INDEX IF NOT EXISTS idx_analytics_created_at ON analytics_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_sop_slug ON analytics_events(sop_slug);

-- ============================================================
-- Updated_at trigger helper
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trg_sop_flows_updated_at
    BEFORE UPDATE ON sop_flows
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER trg_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER trg_escalations_updated_at
    BEFORE UPDATE ON escalations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
