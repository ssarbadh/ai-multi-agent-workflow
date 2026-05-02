"""add rag_sources to messages

Revision ID: 007
Revises: 006
Create Date: 2026-02-07 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add rag_sources column to messages table
    op.add_column('messages', sa.Column('rag_sources', postgresql.JSON(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    # Remove rag_sources column from messages table
    op.drop_column('messages', 'rag_sources')
