"""OpenAPI to MCP Bridge - converts OpenAPI specs to MCP tools."""

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml

from app.core.config import settings
from app.core.logging import logger
from app.models.schemas import (
    OpenAPIConversionRequest,
    OpenAPIConversionResult,
    OpenAPISpec,
    ToolDefinition,
    ToolInputSchema,
)


class OpenAPIBridge:
    """Converts OpenAPI specifications to MCP tools."""

    def __init__(self):
        self._specs: Dict[str, OpenAPISpec] = {}
        self._http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self) -> None:
        """Initialize the bridge."""
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # Load specs from configured path
        specs_path = Path(settings.OPENAPI_SPECS_PATH)
        if specs_path.exists():
            for spec_file in specs_path.glob("*.yaml"):
                await self.load_spec_from_file(str(spec_file))
            for spec_file in specs_path.glob("*.json"):
                await self.load_spec_from_file(str(spec_file))

        logger.info(f"OpenAPI bridge initialized with {len(self._specs)} specs")

    async def shutdown(self) -> None:
        """Shutdown the bridge."""
        if self._http_client:
            await self._http_client.aclose()

    async def load_spec_from_file(self, file_path: str) -> Optional[OpenAPISpec]:
        """Load an OpenAPI spec from a file."""
        try:
            path = Path(file_path)
            if not path.exists():
                return None

            content = path.read_text()
            if file_path.endswith(".yaml") or file_path.endswith(".yml"):
                spec_data = yaml.safe_load(content)
            else:
                spec_data = json.loads(content)

            spec_id = hashlib.md5(content.encode()).hexdigest()[:8]
            info = spec_data.get("info", {})

            spec = OpenAPISpec(
                spec_id=spec_id,
                name=info.get("title", path.stem),
                version=info.get("version", "1.0.0"),
                file_path=file_path,
            )
            self._specs[spec_id] = spec

            logger.info(f"Loaded OpenAPI spec: {spec.name}", spec_id=spec_id)
            return spec

        except Exception as e:
            logger.error(f"Failed to load spec: {e}", file_path=file_path)
            return None

    async def load_spec_from_url(self, url: str) -> Optional[OpenAPISpec]:
        """Load an OpenAPI spec from a URL."""
        try:
            response = await self._http_client.get(url)
            response.raise_for_status()

            content = response.text
            if url.endswith(".yaml") or url.endswith(".yml"):
                spec_data = yaml.safe_load(content)
            else:
                spec_data = json.loads(content)

            spec_id = hashlib.md5(content.encode()).hexdigest()[:8]
            info = spec_data.get("info", {})

            spec = OpenAPISpec(
                spec_id=spec_id,
                name=info.get("title", "Unknown"),
                version=info.get("version", "1.0.0"),
                url=url,
            )
            self._specs[spec_id] = spec

            logger.info(f"Loaded OpenAPI spec from URL: {spec.name}", spec_id=spec_id)
            return spec

        except Exception as e:
            logger.error(f"Failed to load spec from URL: {e}", url=url)
            return None

    def convert_to_tools(
        self,
        spec_data: Dict[str, Any],
        server_id: str,
        include_paths: Optional[List[str]] = None,
        exclude_paths: Optional[List[str]] = None,
    ) -> OpenAPIConversionResult:
        """Convert OpenAPI spec to MCP tools."""
        tools = []
        errors = []

        paths = spec_data.get("paths", {})
        base_url = self._get_base_url(spec_data)

        for path, path_item in paths.items():
            # Check include/exclude filters
            if include_paths and not any(path.startswith(p) for p in include_paths):
                continue
            if exclude_paths and any(path.startswith(p) for p in exclude_paths):
                continue

            for method, operation in path_item.items():
                if method not in ("get", "post", "put", "patch", "delete"):
                    continue

                try:
                    tool = self._convert_operation_to_tool(
                        path=path,
                        method=method,
                        operation=operation,
                        server_id=server_id,
                        base_url=base_url,
                        spec_data=spec_data,
                    )
                    if tool:
                        tools.append(tool)
                except Exception as e:
                    errors.append(f"Error converting {method.upper()} {path}: {str(e)}")

        return OpenAPIConversionResult(
            server_id=server_id,
            tools_created=len(tools),
            tools=tools,
            errors=errors,
        )

    def _get_base_url(self, spec_data: Dict[str, Any]) -> str:
        """Extract base URL from OpenAPI spec."""
        servers = spec_data.get("servers", [])
        if servers:
            return servers[0].get("url", "")
        return ""

    def _convert_operation_to_tool(
        self,
        path: str,
        method: str,
        operation: Dict[str, Any],
        server_id: str,
        base_url: str,
        spec_data: Dict[str, Any],
    ) -> Optional[ToolDefinition]:
        """Convert a single OpenAPI operation to an MCP tool."""
        operation_id = operation.get("operationId")
        if not operation_id:
            # Generate operation ID from path and method
            clean_path = re.sub(r"[{}]", "", path).replace("/", "_").strip("_")
            operation_id = f"{method}_{clean_path}"

        # Build tool name
        tool_name = f"api_{operation_id}"

        # Build description
        summary = operation.get("summary", "")
        description = operation.get("description", summary)
        if not description:
            description = f"{method.upper()} {path}"

        # Build input schema from parameters and request body
        input_schema = self._build_input_schema(operation, spec_data)

        return ToolDefinition(
            name=tool_name,
            description=description,
            inputSchema=input_schema,
            server_id=server_id,
        )

    def _build_input_schema(
        self,
        operation: Dict[str, Any],
        spec_data: Dict[str, Any],
    ) -> ToolInputSchema:
        """Build input schema from OpenAPI operation."""
        properties = {}
        required = []

        # Process parameters
        for param in operation.get("parameters", []):
            param_name = param.get("name")
            param_schema = param.get("schema", {"type": "string"})

            properties[param_name] = {
                "type": param_schema.get("type", "string"),
                "description": param.get("description", ""),
            }

            if param.get("required"):
                required.append(param_name)

        # Process request body
        request_body = operation.get("requestBody", {})
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        body_schema = json_content.get("schema", {})

        if body_schema:
            # Resolve $ref if present
            if "$ref" in body_schema:
                body_schema = self._resolve_ref(body_schema["$ref"], spec_data)

            body_props = body_schema.get("properties", {})
            for prop_name, prop_schema in body_props.items():
                properties[prop_name] = {
                    "type": prop_schema.get("type", "string"),
                    "description": prop_schema.get("description", ""),
                }

            body_required = body_schema.get("required", [])
            required.extend(body_required)

        return ToolInputSchema(
            type="object",
            properties=properties,
            required=list(set(required)),
        )

    def _resolve_ref(self, ref: str, spec_data: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve a $ref pointer in the spec."""
        if not ref.startswith("#/"):
            return {}

        parts = ref[2:].split("/")
        current = spec_data

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return {}

        return current if isinstance(current, dict) else {}

    def list_specs(self) -> List[OpenAPISpec]:
        """List all loaded specs."""
        return list(self._specs.values())


# Global instance
openapi_bridge = OpenAPIBridge()
