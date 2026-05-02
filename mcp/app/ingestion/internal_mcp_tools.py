"""In-process MCP tool calls for graph enrichment (bypasses HTTP auth).

Anonymous / viewer API clients cannot execute tools. Enrichment runs inside the
MCP process and should call the gateway with an admin-equivalent user instead
of looping back through /api/v1/tools/call without execute permission.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.core.logging import logger
from app.core.security import MCPUser, get_permissions_for_roles
from app.models.schemas import ToolCallRequest
from app.services.gateway import gateway


def _enrichment_user() -> MCPUser:
    return MCPUser(
        id="graph-enrichment-internal",
        roles={"admin"},
        permissions=get_permissions_for_roles(["admin"]),
    )


async def call_tool_for_enrichment(
    name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute an MCP tool via the gateway with full tool permissions.
    Returns parsed JSON from the first text content block, or {} on failure.
    """
    user = _enrichment_user()
    try:
        resp = await gateway.route_tool_call(
            ToolCallRequest(name=name, arguments=arguments),
            user=user,
        )
    except Exception as exc:
        logger.warning("Enrichment internal tool call failed", tool=name, exc=str(exc))
        return {}
    if resp.isError:
        text = ""
        if resp.content and isinstance(resp.content[0], dict):
            text = str(resp.content[0].get("text", ""))
        logger.warning("Enrichment tool returned error", tool=name, detail=text[:200])
        return {}
    if not resp.content:
        return {}
    first = resp.content[0]
    if not isinstance(first, dict):
        return {}
    text = first.get("text", "")
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Enrichment tool returned non-JSON text", tool=name, preview=text[:500])
        return {}
    if isinstance(data, dict) and data.get("error"):
        logger.warning(
            "Enrichment tool Kubernetes/backend error",
            tool=name,
            error=str(data.get("error"))[:800],
        )
    return data if isinstance(data, dict) else {}
