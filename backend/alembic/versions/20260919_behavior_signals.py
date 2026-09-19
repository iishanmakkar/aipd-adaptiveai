"""behavior_signals table for wired behavior-adaptive policy (B2)

Revision ID: 20260919_behavior_signals
Revises: 20260915_add_disability_profile
Create Date: 2026-09-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260919_behavior_signals'
down_revision = '20260915_add_disability_profile'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'behavior_signals',
        sa.Column('session_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sessions.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('replay_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skip_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('listen_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('listen_seconds', sa.Float(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('behavior_signals')
