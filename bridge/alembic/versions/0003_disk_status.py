"""disk_status tablosu — M7 disk doluluk izleme

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-08

DiskMonitor (bridge/disk.py) her tur disk doluluğu + snapshot dizini boyutunu
bu tabloya upsert eder (mount başına tek satır, camera_status gibi). Grafana
"Disk Doluluk" paneli buradan okur; `alert_sent` flag'i eşik alarmının
tek-uyarı + histerezis durumunu restart-safe tutar.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS disk_status (
            mount TEXT PRIMARY KEY,
            checked_at TIMESTAMPTZ,
            used_pct REAL NOT NULL DEFAULT 0,
            used_bytes BIGINT NOT NULL DEFAULT 0,
            total_bytes BIGINT NOT NULL DEFAULT 0,
            snapshot_bytes BIGINT NOT NULL DEFAULT 0,
            snapshot_files INTEGER NOT NULL DEFAULT 0,
            last_pruned_at TIMESTAMPTZ,
            pruned_files_last INTEGER NOT NULL DEFAULT 0,
            alert_sent BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB DEFAULT '{}'::jsonb
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS disk_status")
