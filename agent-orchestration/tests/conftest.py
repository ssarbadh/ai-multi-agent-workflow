"""Pytest configuration for agent-orchestration tests."""

import os
import sys
from pathlib import Path

# Add parent directory to path
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

# Load .env file from agent-orchestration directory
from dotenv import load_dotenv
env_path = parent_dir / ".env"
load_dotenv(env_path)

# Set default test environment variables if not present
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/aegisops")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/2")
os.environ.setdefault("LLM_API_KEY", "test_key")
os.environ.setdefault("SNOW_INSTANCE_URL", "https://test.service-now.com")
os.environ.setdefault("SNOW_USERNAME", "test")
os.environ.setdefault("SNOW_PASSWORD", "test")
os.environ.setdefault("SMTP_HOST", "smtp.test.com")
os.environ.setdefault("SMTP_USERNAME", "test")
os.environ.setdefault("SMTP_PASSWORD", "test")
os.environ.setdefault("SMTP_FROM_EMAIL", "test@test.com")
