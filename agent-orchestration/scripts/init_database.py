"""Initialize database with tables and seed data."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import init_db, engine
from app.core.config import settings


async def main():
    """Initialize database."""
    print(f"Initializing database: {settings.DATABASE_URL}")
    
    try:
        await init_db()
        print("✓ Database tables created successfully")
        
        # Test connection
        async with engine.begin() as conn:
            result = await conn.execute("SELECT 1")
            print("✓ Database connection verified")
        
        print("\nDatabase initialization complete!")
        
    except Exception as e:
        print(f"✗ Database initialization failed: {e}")
        sys.exit(1)
    
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
