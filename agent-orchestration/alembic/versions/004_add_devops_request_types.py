"""Add devops_automation and conversational to RequestType enum

Revision ID: 004
Revises: 003
Create Date: 2026-01-25 18:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add new enum values to RequestType."""
    # PostgreSQL requires ALTER TYPE to add new enum values
    op.execute("ALTER TYPE requesttype ADD VALUE IF NOT EXISTS 'DEVOPS_AUTOMATION'")
    op.execute("ALTER TYPE requesttype ADD VALUE IF NOT EXISTS 'CONVERSATIONAL'")


def downgrade() -> None:
    """Downgrade not supported for enum value additions in PostgreSQL."""
    # PostgreSQL doesn't support removing enum values directly
    # Would require recreating the enum type and updating all references
    pass
