#!/usr/bin/env python3
"""
Example graph enrichment ingestion script.

Requires: pip install -r mcp/requirements.txt  (or run inside MCP Docker container)

Usage:
  # From mcp directory:
  cd mcp && python -m scripts.run_graph_ingestion  # if scripts is a package
  # Or: cd mcp && python ../scripts/run_graph_ingestion.py

  # Via load endpoint (when MCP is running) - preferred:
  curl -X POST http://localhost:8005/api/v1/graph/load \
    -H "Content-Type: application/json" \
    -d '{"use_simulated": true, "create_incident": true}'
"""

import argparse
import os
import sys

# Add project root and mcp to path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_script_dir)
_mcp = os.path.join(_root, "mcp")
if _mcp not in sys.path:
    sys.path.insert(0, _mcp)
os.chdir(_mcp)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
    load_dotenv(os.path.join(_mcp, ".env"), override=False)
except ImportError:
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Run graph enrichment ingestion")
    parser.add_argument("--services", nargs="+", help="Service names to enrich")
    parser.add_argument("--no-simulated", action="store_true", help="Use real Prometheus/logs")
    parser.add_argument("--create-incident", action="store_true", help="Create sample Incident node")
    parser.add_argument("--no-databases", action="store_true", help="Skip database ingestion")
    parser.add_argument("--no-istio", action="store_true", help="Skip Istio call graph ingestion")
    args = parser.parse_args()

    from app.ingestion.runner import run_enrichment

    result = run_enrichment(
        services=args.services,
        use_simulated=not args.no_simulated,
        create_incident=args.create_incident,
        ingest_databases=not args.no_databases,
        ingest_istio=not args.no_istio,
    )
    print("Enrichment result:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    if result.get("errors"):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
