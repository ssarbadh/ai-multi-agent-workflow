#!/usr/bin/env python3
"""
AegisOps RAG Service Runner

Usage:
    python run.py              # Start service with auto-reload
    python run.py --no-reload  # Start without auto-reload
"""

import sys
import subprocess
import argparse
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def start_service(host="0.0.0.0", port=8001, reload=True):
    """Start the RAG service."""
    print("=" * 60)
    print("AegisOps RAG Service")
    print("=" * 60)
    print(f"Port: {port}")
    print(f"API Docs: http://localhost:{port}/docs")
    print("=" * 60)
    
    cmd = ["uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")
    
    try:
        subprocess.run(cmd, cwd=project_root, check=True)
    except KeyboardInterrupt:
        print("\n✅ Service stopped")


def main():
    parser = argparse.ArgumentParser(description="RAG Service Runner")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8001, help="Port to bind to")
    parser.add_argument("--no-reload", action="store_true", help="Disable auto-reload")
    
    args = parser.parse_args()
    start_service(host=args.host, port=args.port, reload=not args.no_reload)


if __name__ == "__main__":
    main()
