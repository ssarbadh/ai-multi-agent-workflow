"""
Debug CLI for the SRE LangGraph: run the full graph or a single node from JSON state.

Usage (from agent-orchestration with app on PYTHONPATH, or: pip install -e .):

  export PYTHONPATH=.
  python -m app.cli.sre_agent_cli node rca_agent \\
    --state-file app/cli/fixtures/rca_agent_example_state.json \\
    --no-persist

LangSmith: set LANGCHAIN_TRACING_V2=true, LANGCHAIN_API_KEY, and optionally LANGCHAIN_PROJECT
in .env or the environment before running (same as the API server).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Graph node name -> private coroutine name on SREMultiAgent
NODE_METHODS: Dict[str, str] = {
    "incident_trigger": "_incident_trigger_node",
    "context_aggregation": "_context_aggregation_node",
    "rca_agent": "_rca_agent_node",
    "critique_agent": "_critique_agent_node",
    "confidence_scoring": "_confidence_scoring_node",
    "web_search_agent": "_web_search_agent_node",
    "rca_agent_recompute": "_rca_agent_recompute_node",
    "remediation_plan": "_remediation_plan_node",
    "human_approval": "_human_approval_node",
    "await_approval": "_await_approval_node",
    "remediation_execution": "_remediation_execution_node",
    "manual_remediation_fallback": "_manual_remediation_fallback_node",
    "servicenow_update": "_servicenow_update_node",
    "context_graph_update": "_context_graph_update_node",
}


def _load_state(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("State file must be a JSON object")
    return data


def _apply_no_persist(agent: Any) -> None:
    """Skip Redis writes so local debugging does not require Redis."""

    async def _noop_persist(state: Dict[str, Any]) -> None:
        state["updated_at"] = datetime.utcnow().isoformat()

    agent._persist_state = _noop_persist  # type: ignore[assignment]


async def _run_node(agent: Any, node: str, state: Dict[str, Any]) -> Dict[str, Any]:
    method_name = NODE_METHODS[node]
    method: Callable[..., Coroutine[Any, Any, Dict[str, Any]]] = getattr(agent, method_name)
    return await method(state)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run SRE multi-agent graph or one node from a JSON state file.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_node = sub.add_parser("node", help="Run a single LangGraph node (e.g. rca_agent)")
    p_node.add_argument(
        "node_name",
        choices=sorted(NODE_METHODS.keys()),
        help="Name of the graph node to invoke",
    )
    p_node.add_argument(
        "--state-file",
        type=Path,
        required=True,
        help="Path to JSON object matching SREMultiAgentState fields needed by that node",
    )
    p_node.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write state to Redis (recommended for local debugging)",
    )
    p_node.add_argument(
        "--output",
        type=Path,
        help="Write resulting state JSON to this file (default: stdout)",
    )

    p_wf = sub.add_parser("workflow", help="Run the full main LangGraph from initial state")
    p_wf.add_argument(
        "--state-file",
        type=Path,
        required=True,
        help="JSON state; must include incident_id and fields required by early nodes",
    )
    p_wf.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write state to Redis",
    )
    p_wf.add_argument(
        "--output",
        type=Path,
        help="Write final state JSON to this file",
    )

    p_post = sub.add_parser(
        "post-approval",
        help="Run post-approval subgraph (remediation_execution -> ... -> END)",
    )
    p_post.add_argument(
        "--state-file",
        type=Path,
        required=True,
        help="State after human approval (approved, remediation plan, etc.)",
    )
    p_post.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not write state to Redis",
    )
    p_post.add_argument(
        "--output",
        type=Path,
        help="Write final state JSON to this file",
    )

    p_list = sub.add_parser("list-nodes", help="Print graph node names for use with `node`")

    return parser.parse_args()


def _emit_state(state: Dict[str, Any], output: Path | None) -> None:
    text = json.dumps(state, indent=2, default=str)
    if output:
        output.write_text(text, encoding="utf-8")
        print(f"Wrote state to {output}", file=sys.stderr)
    else:
        print(text)


async def _async_main(args: argparse.Namespace) -> int:
    # Load .env from agent-orchestration root (parent of app/)
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env")
    load_dotenv()

    from app.core.langsmith_setup import configure_langsmith_from_settings

    configure_langsmith_from_settings()

    if args.command == "list-nodes":
        for name in sorted(NODE_METHODS.keys()):
            print(name)
        return 0

    from app.agents.sre_multi_agent import sre_multi_agent

    state = _load_state(args.state_file)

    if args.no_persist:
        _apply_no_persist(sre_multi_agent)

    if args.command == "node":
        out = await _run_node(sre_multi_agent, args.node_name, state)
        _emit_state(out, args.output)
        return 0

    incident_id = state.get("incident_id")
    if not incident_id or not isinstance(incident_id, str):
        print("state must include a string incident_id", file=sys.stderr)
        return 2

    cfg = sre_multi_agent._langgraph_run_config(incident_id, "cli_workflow")

    if args.command == "workflow":
        final = await sre_multi_agent.workflow.ainvoke(state, config=cfg)
        _emit_state(final, args.output)
        return 0

    if args.command == "post-approval":
        final = await sre_multi_agent.post_approval_workflow.ainvoke(state, config=cfg)
        _emit_state(final, args.output)
        return 0

    return 1


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        raise SystemExit(asyncio.run(_async_main(args)))
    except KeyboardInterrupt:
        raise SystemExit(130)


if __name__ == "__main__":
    main()
