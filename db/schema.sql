-- AI NVR şeması — M1 baseline (referans)
--
-- Üretim ortamında Alembic migrasyonu kullanılır:
--   bridge/alembic/versions/0001_init.py
--
-- Bu dosya hızlı referans için tutulur. Şema değişikliklerinde önce
-- Alembic revisyonu oluşturup buraya senkronize et.

CREATE TABLE IF NOT EXISTS zone_events (
    id BIGSERIAL PRIMARY KEY,
    zone TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- 'first_entry' | 'still_present' | 'exit' | 'unauthorized'
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    score REAL,
    frigate_event_id TEXT,
    snapshot_path TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    dahua_alarm_sent BOOLEAN DEFAULT FALSE,
    dahua_alarm_retry_count INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_zone_events_zone_ts ON zone_events (zone, ts DESC);
CREATE INDEX IF NOT EXISTS idx_zone_events_event_type ON zone_events (event_type, ts DESC);

CREATE TABLE IF NOT EXISTS door_events (
    id BIGSERIAL PRIMARY KEY,
    zone TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    entry_ts TIMESTAMPTZ(3) NOT NULL,   -- ms hassasiyet
    exit_ts TIMESTAMPTZ(3),
    duration_ms INT,
    direction TEXT,                      -- 'in' | 'out' | 'unknown'
    tracking_id TEXT,
    entry_snapshot_path TEXT,
    exit_snapshot_path TEXT,
    clip_path TEXT,
    email_sent BOOLEAN DEFAULT FALSE,
    view_token TEXT UNIQUE,              -- HMAC viewer token
    view_token_expires_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_door_events_zone_ts ON door_events (zone, entry_ts DESC);
CREATE INDEX IF NOT EXISTS idx_door_events_view_token ON door_events (view_token);

CREATE TABLE IF NOT EXISTS llm_usage (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    call_type TEXT NOT NULL,             -- 'truck_color' | 'anomaly' | 'unauthorized'
    model TEXT NOT NULL,
    input_tokens INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    cached_input_tokens INT NOT NULL DEFAULT 0,
    cost_usd NUMERIC(10,6) NOT NULL DEFAULT 0,
    latency_ms INT,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error TEXT,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_ts ON llm_usage (ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_call_type ON llm_usage (call_type, ts DESC);

CREATE TABLE IF NOT EXISTS truck_events (
    id BIGSERIAL PRIMARY KEY,
    camera_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cekici_rengi TEXT,
    dorse_var_mi BOOLEAN,
    dorse_rengi TEXT,
    dorse_tipi TEXT,                     -- 'tenteli'|'frigo'|'konteyner'|'acik'|'tanker'|'bilinmeyen'
    yon TEXT,                            -- 'giris'|'cikis'|'duruyor'
    guven REAL,
    notlar TEXT,
    snapshot_path TEXT,
    llm_usage_id BIGINT REFERENCES llm_usage (id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_truck_events_ts ON truck_events (ts DESC);
-- Dedup sorgusu (truck_event_exists) için: metadata->>'frigate_event_id' (0002)
CREATE INDEX IF NOT EXISTS idx_truck_events_frigate_event_id
    ON truck_events ((metadata->>'frigate_event_id'));

CREATE TABLE IF NOT EXISTS camera_status (
    camera_id TEXT PRIMARY KEY,
    last_seen_at TIMESTAMPTZ,
    is_online BOOLEAN NOT NULL DEFAULT FALSE,
    last_event_at TIMESTAMPTZ,
    offline_alert_sent BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'::jsonb
);
