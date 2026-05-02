"""add cloudops and sre request types

Revision ID: 005
Revises: 004
Create Date: 2026-01-26 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    """Add CLOUDOPS and SRE to RequestType enum."""
    # Add new enum values to existing enum type
    op.execute("ALTER TYPE requesttype ADD VALUE IF NOT EXISTS 'CLOUDOPS'")
    op.execute("ALTER TYPE requesttype ADD VALUE IF NOT EXISTS 'SRE'")


def downgrade():
    """Remove CLOUDOPS and SRE from RequestType enum."""
    # Note: PostgreSQL doesn't support removing enum values directly
    # This would require recreating the enum type, which is complex
    # For production, consider creating a new enum type and migrating data
    pass
