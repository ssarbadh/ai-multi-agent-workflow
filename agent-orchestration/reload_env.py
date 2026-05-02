#!/usr/bin/env python3
"""Reload environment variables from .env file and restart the service."""

import os
import sys
from pathlib import Path

# Load .env file
env_file = Path("/app/.env")
if env_file.exists():
    print(f"Loading environment from {env_file}")
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key] = value
                print(f"Set {key}={value[:20]}..." if len(value) > 20 else f"Set {key}={value}")
    
    # Verify critical LLM variables
    print("\n=== LLM Configuration ===")
    print(f"LLM_PROVIDER: {os.getenv('LLM_PROVIDER')}")
    print(f"LLM_MODEL: {os.getenv('LLM_MODEL')}")
    print(f"LLM_BASE_URL: {os.getenv('LLM_BASE_URL')}")
    print(f"LLM_API_KEY: {os.getenv('LLM_API_KEY', '')[:20]}...")
    
    # Restart the service by exiting (Docker will restart it)
    print("\nEnvironment reloaded. Exiting to trigger restart...")
    sys.exit(0)
else:
    print(f"Error: {env_file} not found")
    sys.exit(1)
