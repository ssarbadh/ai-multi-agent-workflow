"""Add document_type column to haystack_rag_documents

Revision ID: 003
Revises: 002
Create Date: 2026-02-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    """Add document_type column for filtering."""
    # Add document_type column to haystack table
    op.execute("""
        ALTER TABLE haystack_rag_documents 
        ADD COLUMN IF NOT EXISTS document_type VARCHAR(100) DEFAULT 'general';
    """)
    
    # Create index for efficient filtering
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_haystack_rag_documents_document_type 
        ON haystack_rag_documents(document_type);
    """)
    
    # Update existing documents based on their source
    op.execute("""
        UPDATE haystack_rag_documents 
        SET document_type = CASE 
            WHEN meta->>'source' = 'k8s_training_data' THEN 'incident'
            WHEN meta->>'source' = 'google_drive' AND meta->>'title' ILIKE '%incident%' THEN 'incident'
            WHEN meta->>'source' = 'google_drive' AND meta->>'title' ILIKE '%runbook%' THEN 'runbook'
            WHEN meta->>'source' = 'google_drive' AND meta->>'title' ILIKE '%sop%' THEN 'procedure'
            ELSE 'general'
        END
        WHERE document_type = 'general' OR document_type IS NULL;
    """)


def downgrade():
    """Remove document_type column."""
    op.execute("DROP INDEX IF EXISTS ix_haystack_rag_documents_document_type;")
    op.execute("ALTER TABLE haystack_rag_documents DROP COLUMN IF EXISTS document_type;")
