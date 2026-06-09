"""service_status tablosu — M7 Frigate servis down-detection

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-08

FrigateMonitor (bridge/frigate_monitor.py) `frigate/available` LWT'sinden Frigate
servis durumunu bu tabloya yazar (servis başına tek satır; ileride başka servisler
de eklenebilir). `offline_alert_sent` flag'i tek-uyarı + recovery'yi restart-safe tutar;
Grafana "Frigate Servisi" paneli buradan okur.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS service_status (
            service TEXT PRIMARY KEY,
            is_online BOOLEAN NOT NULL DEFAULT FALSE,
            last_change_at TIMESTAMPTZ,
            offline_alert_sent BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB DEFAULT '{}'::jsonb
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS service_status")
