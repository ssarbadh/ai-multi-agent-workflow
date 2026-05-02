"""Add sessions and messages tables

Revision ID: 002
Revises: 001
Create Date: 2026-01-25 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # Create sessions table
    op.create_table(
        'sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('snow_ticket_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sessions_status', 'sessions', ['status'])
    op.create_index('ix_sessions_type', 'sessions', ['type'])
    op.create_index('ix_sessions_created_at', 'sessions', ['created_at'])
    op.create_index('ix_sessions_snow_ticket_id', 'sessions', ['snow_ticket_id'])
    
    # Create messages table
    op.create_table(
        'messages',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=True),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('confidentiality_score', sa.Float(), nullable=True),
        sa.Column('confidentiality_label', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE')
    )
    op.create_index('ix_messages_session_id', 'messages', ['session_id'])
    op.create_index('ix_messages_run_id', 'messages', ['run_id'])
    op.create_index('ix_messages_created_at', 'messages', ['created_at'])
    
    # Add foreign key to runs table
    op.create_foreign_key(
        'fk_runs_session_id',
        'runs', 'sessions',
        ['session_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade():
    # Drop foreign key from runs
    op.drop_constraint('fk_runs_session_id', 'runs', type_='foreignkey')
    
    # Drop messages table
    op.drop_index('ix_messages_created_at', 'messages')
    op.drop_index('ix_messages_run_id', 'messages')
    op.drop_index('ix_messages_session_id', 'messages')
    op.drop_table('messages')
    
    # Drop sessions table
    op.drop_index('ix_sessions_snow_ticket_id', 'sessions')
    op.drop_index('ix_sessions_created_at', 'sessions')
    op.drop_index('ix_sessions_type', 'sessions')
    op.drop_index('ix_sessions_status', 'sessions')
    op.drop_table('sessions')
