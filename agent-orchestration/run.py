#!/usr/bin/env python3
"""
AegisOps CloudOps Service Runner

Usage:
    python run.py              # Start service with auto-reload
    python run.py --no-reload  # Start without auto-reload
    python run.py --port 8003  # Start on custom port
    python run.py --migrate    # Run migrations then start
    python run.py --help       # Show help
"""

import sys
import os
import subprocess
import argparse
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def run_migrations():
    """Run Alembic migrations."""
    print("=" * 60)
    print("Running database migrations...")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True
        )
        print(result.stdout)
        print("✅ Migrations completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Migration failed: {e}")
        print(e.stderr)
        return False
    except FileNotFoundError:
        print("❌ Alembic not found. Please install: pip install alembic")
        return False


def check_environment():
    """Check if required environment variables are set."""
    required_vars = [
        "DATABASE_URL",
        "REDIS_URL",
        "LLM_API_KEY",
        "GITHUB_TOKEN"
    ]
    
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    if missing:
        print("⚠️  Warning: Missing environment variables:")
        for var in missing:
            print(f"   - {var}")
        print("\nMake sure .env file exists and contains all required variables.")
        print()


def start_service(host="0.0.0.0", port=8002, reload=True):
    """Start the FastAPI service using uvicorn."""
    print("=" * 60)
    print("AegisOps CloudOps Service")
    print("=" * 60)
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Auto-reload: {reload}")
    print(f"API Docs: http://localhost:{port}/docs")
    print("=" * 60)
    print()
    print("Press Ctrl+C to stop the service")
    print()
    
    # Check environment
    # check_environment()
    
    # Build uvicorn command
    cmd = [
        "uvicorn",
        "app.main:app",
        "--host", host,
        "--port", str(port)
    ]
    
    if reload:
        cmd.append("--reload")
    
    try:
        subprocess.run(cmd, cwd=project_root, check=True)
    except KeyboardInterrupt:
        print("\n\n✅ Service stopped")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Service failed: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print("❌ Uvicorn not found. Please install: pip install uvicorn")
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="AegisOps CloudOps Service Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py                    # Start with auto-reload
  python run.py --no-reload        # Start without auto-reload
  python run.py --port 8003        # Start on port 8003
  python run.py --migrate          # Run migrations first
  python run.py --host 127.0.0.1   # Bind to localhost only
        """
    )
    
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8002,
        help="Port to bind to (default: 8002)"
    )
    
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable auto-reload"
    )
    
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Run database migrations before starting"
    )
    
    args = parser.parse_args()
    
    # Run migrations if requested
    if args.migrate:
        if not run_migrations():
            print("\n❌ Migrations failed. Exiting.")
            sys.exit(1)
        print()
    
    # Start service
    start_service(
        host=args.host,
        port=args.port,
        reload=not args.no_reload
    )


if __name__ == "__main__":
    main()
