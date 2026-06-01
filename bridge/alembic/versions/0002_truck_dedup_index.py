"""truck_events dedup index: metadata->>'frigate_event_id'

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-01

`truck_event_exists` dedup sorgusu `metadata->>'frigate_event_id'` üzerinde
çalışıyor (snapshot-gated dedup'ta snapshot-pending window boyunca her event'te
çağrılabilir). 0001'de bu ifade için index yoktu → seq scan. Expression index
ile dedup sorgusu hızlanır.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_truck_events_frigate_event_id
        ON truck_events ((metadata->>'frigate_event_id'))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_truck_events_frigate_event_id")
