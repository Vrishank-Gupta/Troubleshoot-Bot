-- ── Product hierarchy ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_categories (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS product_families (
    id          TEXT PRIMARY KEY,
    category_id TEXT REFERENCES product_categories(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(category_id, name)
);

-- Extend existing products table with hierarchy links
ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id   TEXT REFERENCES product_categories(id) ON DELETE SET NULL;
ALTER TABLE products ADD COLUMN IF NOT EXISTS family_id     TEXT REFERENCES product_families(id)   ON DELETE SET NULL;
ALTER TABLE products ADD COLUMN IF NOT EXISTS model_number  TEXT;

-- ── SOP scope & hierarchy ──────────────────────────────────────────────────────
ALTER TABLE sop_flows ADD COLUMN IF NOT EXISTS scope       TEXT DEFAULT 'model';   -- generic|category|family|model
ALTER TABLE sop_flows ADD COLUMN IF NOT EXISTS category_id TEXT REFERENCES product_categories(id) ON DELETE SET NULL;
ALTER TABLE sop_flows ADD COLUMN IF NOT EXISTS family_id   TEXT REFERENCES product_families(id)   ON DELETE SET NULL;

-- ── Model-specific step overrides ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sop_overrides (
    id           TEXT PRIMARY KEY,
    base_sop_id  TEXT NOT NULL REFERENCES sop_flows(id) ON DELETE CASCADE,
    product_id   TEXT REFERENCES products(id) ON DELETE CASCADE,
    step_id      TEXT NOT NULL,
    override_json JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── Performance indexes ────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_conversations_customer_id   ON conversations(customer_id);
CREATE INDEX IF NOT EXISTS idx_conversations_status        ON conversations(status);
CREATE INDEX IF NOT EXISTS idx_conversations_created_at    ON conversations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sop_flows_status            ON sop_flows(status);
CREATE INDEX IF NOT EXISTS idx_sop_flows_product_id        ON sop_flows(product_id);
CREATE INDEX IF NOT EXISTS idx_sop_flows_scope             ON sop_flows(scope);
CREATE INDEX IF NOT EXISTS idx_sop_flows_category_id       ON sop_flows(category_id);
CREATE INDEX IF NOT EXISTS idx_sop_flows_family_id         ON sop_flows(family_id);
CREATE INDEX IF NOT EXISTS idx_sop_chunks_product_id       ON sop_chunks(product_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_conv_id    ON analytics_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_created_at ON analytics_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_product_families_cat_id     ON product_families(category_id);
CREATE INDEX IF NOT EXISTS idx_products_family_id          ON products(family_id);
CREATE INDEX IF NOT EXISTS idx_products_category_id        ON products(category_id);

-- ── pgvector HNSW index (fast ANN search) ─────────────────────────────────────
-- Requires pgvector >= 0.5. Skipped automatically if extension not available.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        EXECUTE $sql$
            CREATE INDEX IF NOT EXISTS idx_sop_chunks_embedding_hnsw
                ON sop_chunks USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
        $sql$;
    END IF;
END;
$$;
