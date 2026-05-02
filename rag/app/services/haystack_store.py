"""Haystack document store integration with PostgreSQL + pgvector."""
import logging
from typing import Optional

from haystack.utils import Secret
from haystack_integrations.document_stores.pgvector import PgvectorDocumentStore

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_postgres_document_store() -> PgvectorDocumentStore:
    """
    Get or create PostgreSQL + pgvector document store for Haystack.
    
    Returns:
        Configured PgvectorDocumentStore instance
    """
    try:
        # Parse connection string - remove asyncpg and SSL parameters for psycopg2
        db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        
        # Remove SSL-related query parameters that are not compatible with psycopg2
        if "?" in db_url:
            base_url, params = db_url.split("?", 1)
            # Filter out SSL parameters
            param_pairs = [p for p in params.split("&") if not p.startswith("ssl")]
            if param_pairs:
                db_url = f"{base_url}?{'&'.join(param_pairs)}"
            else:
                db_url = base_url
        
        document_store = PgvectorDocumentStore(
            connection_string=Secret.from_token(db_url),
            table_name="haystack_rag_documents",  # Use Haystack's table with correct schema
            embedding_dimension=settings.rag_embedding_dim,
            vector_function="cosine_similarity",
            recreate_table=False,  # Don't recreate to preserve data
            search_strategy="hnsw"
        )
        
        logger.info("PostgreSQL document store initialized")
        return document_store
        
    except Exception as e:
        logger.error(f"Failed to initialize document store: {e}")
        raise


# Singleton instance
_document_store: Optional[PgvectorDocumentStore] = None


def get_document_store() -> PgvectorDocumentStore:
    """Get singleton document store instance."""
    global _document_store
    if _document_store is None:
        _document_store = get_postgres_document_store()
    return _document_store
