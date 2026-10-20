"""composite indexes for hot filter-then-sort queries

Revision ID: 20261007_history_indexes
Revises: 20260919_behavior_signals
Create Date: 2026-10-07

History pagination (messages by session, sessions by user) filters then
ORDER BYs created_at on every page/history/share call. Single-column FK
indexes leave the sort unindexed; these composites cover both.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '20261007_history_indexes'
down_revision = '20260919_behavior_signals'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_session_id_created_at "
        "ON messages (session_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sessions_user_id_created_at "
        "ON sessions (user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_session_id_created_at")
    op.execute("DROP INDEX IF EXISTS ix_sessions_user_id_created_at")
