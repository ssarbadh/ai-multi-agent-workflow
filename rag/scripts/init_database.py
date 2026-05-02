"""
Initialize/Reset RAG Database
Creates all required tables with proper schemas including pgvector extension
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings
from app.models.models import Base


async def init_database():
    """Initialize database with all tables"""
    print("=" * 80)
    print("RAG DATABASE INITIALIZATION")
    print("=" * 80)
    
    # Create engine
    engine = create_async_engine(settings.database_url, echo=True)
    
    print("\n[1/4] Connecting to database...")
    try:
        async with engine.begin() as conn:
            # Test connection
            await conn.execute(text("SELECT 1"))
            print("✓ Connected to PostgreSQL")
            
            # Enable pgvector extension
            print("\n[2/4] Enabling pgvector extension...")
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            print("✓ pgvector extension enabled")
            
            # Drop all existing tables (fresh start)
            print("\n[3/4] Dropping existing tables...")
            await conn.run_sync(Base.metadata.drop_all)
            print("✓ Old tables dropped")
            
            # Create all tables
            print("\n[4/4] Creating new tables...")
            await conn.run_sync(Base.metadata.create_all)
            print("✓ All tables created")
            
            # Verify tables
            result = await conn.execute(text("""
                SELECT tablename FROM pg_tables 
                WHERE schemaname = 'public' 
                ORDER BY tablename
            """))
            tables = result.fetchall()
            
            print("\nCreated tables:")
            for table in tables:
                print(f"  - {table[0]}")
            
            # Create HNSW index on embedding column
            print("\nCreating HNSW vector index...")
            await conn.execute(text("""
                CREATE INDEX IF NOT EXISTS rag_documents_embedding_hnsw_idx 
                ON rag_documents 
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """))
            print("✓ HNSW index created on rag_documents.embedding")
            
    except Exception as e:
        print(f"\n✗ Database initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 80)
    print("✓✓✓ DATABASE INITIALIZED SUCCESSFULLY ✓✓✓")
    print("=" * 80)
    
    return True


if __name__ == "__main__":
    success = asyncio.run(init_database())
    sys.exit(0 if success else 1)
