"""add disability_profile and language_complexity to preferences

Revision ID: 20260915_add_disability_profile
Revises: 91051608e538
Create Date: 2026-09-15

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260915_add_disability_profile'
down_revision = '91051608e538'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create new enum types
    op.execute("CREATE TYPE disabilityprofile AS ENUM ('none', 'blind', 'low_vision', 'cognitive', 'motor')")
    op.execute("CREATE TYPE languagecomplexity AS ENUM ('simple', 'standard', 'technical')")
    
    # Add columns to preferences table
    op.add_column(
        'preferences',
        sa.Column('disability_profile', sa.Enum('none', 'blind', 'low_vision', 'cognitive', 'motor', name='disabilityprofile'), 
                  server_default='none', nullable=False)
    )
    op.add_column(
        'preferences',
        sa.Column('language_complexity', sa.Enum('simple', 'standard', 'technical', name='languagecomplexity'),
                  server_default='standard', nullable=False)
    )


def downgrade() -> None:
    op.drop_column('preferences', 'language_complexity')
    op.drop_column('preferences', 'disability_profile')
    op.execute("DROP TYPE IF EXISTS languagecomplexity")
    op.execute("DROP TYPE IF EXISTS disabilityprofile")