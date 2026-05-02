"""Add workflow state tables

Revision ID: 003
Revises: 002
Create Date: 2026-01-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create workflows table
    op.create_table(
        'workflows',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('repo_name', sa.String(255), nullable=False, index=True),
        sa.Column('environment', sa.String(50), nullable=False, index=True),
        sa.Column('intent', sa.String(50), nullable=False),
        sa.Column('current_state', sa.String(50), nullable=False),
        sa.Column('desired_state', sa.String(50), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, default='RUNNING', index=True),
        sa.Column('metadata', postgresql.JSONB, nullable=True),
        sa.Column('state_snapshot', postgresql.JSONB, nullable=True),
        sa.Column('created_by', sa.String(255), nullable=False),
        sa.Column('feature_branch', sa.String(255), nullable=True, index=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    
    # Create composite index for workflow resolution
    op.create_index(
        'idx_workflow_resolution',
        'workflows',
        ['repo_name', 'environment', 'feature_branch', 'status']
    )
    
    # Create workflow_steps table
    op.create_table(
        'workflow_steps',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workflow_id', sa.String(36), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('step_name', sa.String(100), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, default='PENDING'),
        sa.Column('input', postgresql.JSONB, nullable=True),
        sa.Column('output', postgresql.JSONB, nullable=True),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('executed_by', sa.String(255), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    # Create index for step queries
    op.create_index(
        'idx_workflow_steps_lookup',
        'workflow_steps',
        ['workflow_id', 'step_name', 'status']
    )
    
    # Create workflow_access table for multi-user support
    op.create_table(
        'workflow_access',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workflow_id', sa.String(36), sa.ForeignKey('workflows.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.String(255), nullable=False, index=True),
        sa.Column('role', sa.String(50), nullable=False, default='viewer'),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    
    # Create unique constraint for user access
    op.create_index(
        'idx_workflow_access_unique',
        'workflow_access',
        ['workflow_id', 'user_id'],
        unique=True
    )


def downgrade() -> None:
    op.drop_table('workflow_access')
    op.drop_table('workflow_steps')
    op.drop_table('workflows')
