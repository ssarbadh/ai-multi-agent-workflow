"""Enhance message schema with agent type and parent linkage

Revision ID: 006
Revises: 005
Create Date: 2026-01-27 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add agent_type, parent_message_id, and metadata to messages table."""
    
    # Add new columns
    op.add_column('messages', sa.Column('agent_type', sa.String(), nullable=True))
    op.add_column('messages', sa.Column('parent_message_id', sa.String(), nullable=True))
    op.add_column('messages', sa.Column('metadata', postgresql.JSON(), nullable=True))
    
    # Add foreign key for parent_message_id (self-referential)
    op.create_foreign_key(
        'fk_messages_parent_message_id',
        'messages', 'messages',
        ['parent_message_id'], ['id'],
        ondelete='SET NULL'
    )
    
    # Add index for agent_type (for filtering)
    op.create_index('ix_messages_agent_type', 'messages', ['agent_type'])
    
    # Add index for parent_message_id (for finding responses)
    op.create_index('ix_messages_parent_message_id', 'messages', ['parent_message_id'])
    
    # Add comment to explain the schema
    op.execute("""
        COMMENT ON COLUMN messages.agent_type IS 
        'Type of agent that generated the response: conversational, devops, cloudops, sre';
        
        COMMENT ON COLUMN messages.parent_message_id IS 
        'ID of the user message this response is replying to (for linking user input to agent response)';
        
        COMMENT ON COLUMN messages.metadata IS 
        'Additional metadata: model_name, tokens_used, generation_time_ms, temperature, etc.';
    """)


def downgrade() -> None:
    """Remove agent_type, parent_message_id, and metadata columns."""
    
    # Drop indexes
    op.drop_index('ix_messages_parent_message_id', table_name='messages')
    op.drop_index('ix_messages_agent_type', table_name='messages')
    
    # Drop foreign key
    op.drop_constraint('fk_messages_parent_message_id', 'messages', type_='foreignkey')
    
    # Drop columns
    op.drop_column('messages', 'metadata')
    op.drop_column('messages', 'parent_message_id')
    op.drop_column('messages', 'agent_type')
