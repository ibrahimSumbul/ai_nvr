"""Init: zone_events, door_events, truck_events, llm_usage, camera_status

Revision ID: 0001
Revises:
Create Date: 2026-05-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE zone_events (
            id BIGSERIAL PRIMARY KEY,
            zone TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            score REAL,
            frigate_event_id TEXT,
            snapshot_path TEXT,
            metadata JSONB DEFAULT '{}'::jsonb,
            dahua_alarm_sent BOOLEAN DEFAULT FALSE,
            dahua_alarm_retry_count INT DEFAULT 0
        );
        CREATE INDEX idx_zone_events_zone_ts ON zone_events (zone, ts DESC);
        CREATE INDEX idx_zone_events_event_type ON zone_events (event_type, ts DESC);
        """
    )
    op.execute(
        """
        CREATE TABLE door_events (
            id BIGSERIAL PRIMARY KEY,
            zone TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            entry_ts TIMESTAMPTZ(3) NOT NULL,
            exit_ts TIMESTAMPTZ(3),
            duration_ms INT,
            direction TEXT,
            tracking_id TEXT,
            entry_snapshot_path TEXT,
            exit_snapshot_path TEXT,
            clip_path TEXT,
            email_sent BOOLEAN DEFAULT FALSE,
            view_token TEXT UNIQUE,
            view_token_expires_at TIMESTAMPTZ,
            metadata JSONB DEFAULT '{}'::jsonb
        );
        CREATE INDEX idx_door_events_zone_ts ON door_events (zone, entry_ts DESC);
        CREATE INDEX idx_door_events_view_token ON door_events (view_token);
        """
    )
    op.execute(
        """
        CREATE TABLE llm_usage (
            id BIGSERIAL PRIMARY KEY,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            call_type TEXT NOT NULL,
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
        CREATE INDEX idx_llm_usage_ts ON llm_usage (ts DESC);
        CREATE INDEX idx_llm_usage_call_type ON llm_usage (call_type, ts DESC);
        """
    )
    op.execute(
        """
        CREATE TABLE truck_events (
            id BIGSERIAL PRIMARY KEY,
            camera_id TEXT NOT NULL,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            cekici_rengi TEXT,
            dorse_var_mi BOOLEAN,
            dorse_rengi TEXT,
            dorse_tipi TEXT,
            yon TEXT,
            guven REAL,
            notlar TEXT,
            snapshot_path TEXT,
            llm_usage_id BIGINT REFERENCES llm_usage (id) ON DELETE SET NULL,
            metadata JSONB DEFAULT '{}'::jsonb
        );
        CREATE INDEX idx_truck_events_ts ON truck_events (ts DESC);
        """
    )
    op.execute(
        """
        CREATE TABLE camera_status (
            camera_id TEXT PRIMARY KEY,
            last_seen_at TIMESTAMPTZ,
            is_online BOOLEAN NOT NULL DEFAULT FALSE,
            last_event_at TIMESTAMPTZ,
            offline_alert_sent BOOLEAN DEFAULT FALSE,
            metadata JSONB DEFAULT '{}'::jsonb
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS truck_events")
    op.execute("DROP TABLE IF EXISTS llm_usage")
    op.execute("DROP TABLE IF EXISTS door_events")
    op.execute("DROP TABLE IF EXISTS zone_events")
    op.execute("DROP TABLE IF EXISTS camera_status")
