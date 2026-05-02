"""External Elasticsearch logs adapter server."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings
from app.core.logging import logger
from app.servers.base import BaseMCPServer


class ElasticsearchExternalMCPServer(BaseMCPServer):
    """Adapter that queries Elasticsearch indices directly."""

    TIMESTAMP_CANDIDATES = ("timestamp", "@timestamp", "fluentbit_timestamp")
    SOURCE_CANDIDATES = ("source", "service", "kubernetes.container_name", "kubernetes.labels.service")
    TRACE_CANDIDATES = ("traceId", "trace_id", "trace.id")
    LOG_URL_CANDIDATES = ("logUrl", "log_url", "url")
    MESSAGE_CANDIDATES = ("message", "log", "msg")

    def __init__(self):
        super().__init__(
            name="elasticsearch-server",
            version="0.1.0",
            description="Elasticsearch logs tools for service-level retrieval",
        )
        self._http_client: Optional[httpx.AsyncClient] = None
        self._base_url = settings.ELASTICSEARCH_MCP_URL.rstrip("/")

    async def initialize(self) -> None:
        if not settings.ELASTICSEARCH_MCP_ENABLED:
            logger.info("Elasticsearch adapter disabled by configuration")
            return

        self._http_client = httpx.AsyncClient(
            timeout=settings.ELASTICSEARCH_MCP_TIMEOUT_SECONDS,
            verify=settings.ELASTICSEARCH_MCP_VERIFY_TLS,
        )

        self.register_tool(
            name="elasticsearch_list_indices",
            description="List available Elasticsearch indices",
            handler=self._list_indices,
            input_schema={"type": "object", "properties": {}},
        )
        self.register_tool(
            name="elasticsearch_match_service_indices",
            description="Find Elasticsearch indices matching a service name",
            handler=self._match_service_indices_tool,
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                },
                "required": ["service_name"],
            },
        )
        self.register_tool(
            name="elasticsearch_get_mapping",
            description="Get index mapping from Elasticsearch",
            handler=self._get_mapping_tool,
            input_schema={
                "type": "object",
                "properties": {
                    "index_name": {"type": "string"},
                },
                "required": ["index_name"],
            },
        )
        self.register_tool(
            name="elasticsearch_get_relevant_fields",
            description="Discover relevant log fields (timestamp/source/trace/logUrl) for an index",
            handler=self._get_relevant_fields_tool,
            input_schema={
                "type": "object",
                "properties": {
                    "index_name": {"type": "string"},
                },
                "required": ["index_name"],
            },
        )
        self.register_tool(
            name="elasticsearch_fetch_service_logs",
            description="Fetch service logs from Elasticsearch with source match and timestamp range",
            handler=self._fetch_service_logs,
            input_schema={
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "lookback_minutes": {"type": "number", "default": 60},
                },
                "required": ["service_name"],
            },
        )

        logger.info("Elasticsearch adapter initialized", upstream=self._base_url)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.ELASTICSEARCH_MCP_API_KEY:
            headers["Authorization"] = f"ApiKey {settings.ELASTICSEARCH_MCP_API_KEY}"
        return headers

    def _auth(self) -> Optional[Tuple[str, str]]:
        if settings.ELASTICSEARCH_MCP_USERNAME and settings.ELASTICSEARCH_MCP_PASSWORD:
            return (
                settings.ELASTICSEARCH_MCP_USERNAME,
                settings.ELASTICSEARCH_MCP_PASSWORD,
            )
        return None

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        if not self._http_client:
            raise RuntimeError("Elasticsearch adapter client not initialized")
        url = f"{self._base_url}{path}"
        response = await self._http_client.request(
            method=method,
            url=url,
            params=params,
            json=body,
            headers=self._headers(),
            auth=self._auth(),
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _tool_text(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": "text", "text": json.dumps(payload, ensure_ascii=True)}

    async def _list_indices(self) -> Dict[str, Any]:
        try:
            data = await self._request(
                "GET",
                "/_cat/indices",
                params={"format": "json", "h": "index,health,status,docs.count"},
            )
            indices = [item.get("index") for item in data if isinstance(item, dict) and item.get("index")]
            return self._tool_text(
                {
                    "provider": "elasticsearch",
                    "cluster": self._base_url,
                    "count": len(indices),
                    "indices": indices,
                }
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in {401, 403}:
                return {"type": "text", "text": "Elasticsearch authentication failed. Verify ES credentials/API key."}
            return {"type": "text", "text": f"Elasticsearch list indices failed ({code}): {exc.response.text}"}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"Elasticsearch list indices failed: {exc}"}

    @staticmethod
    def _service_tokens(service_name: str) -> List[str]:
        return [token for token in (service_name or "").lower().replace("_", "-").split("-") if token]

    async def _match_service_indices(self, service_name: str) -> List[str]:
        data = await self._request(
            "GET",
            "/_cat/indices",
            params={"format": "json", "h": "index"},
        )
        indices = [item.get("index") for item in data if isinstance(item, dict) and item.get("index")]
        service_norm = (service_name or "").strip().lower()
        tokens = self._service_tokens(service_norm)
        matched: List[str] = []
        for index in indices:
            idx = (index or "").lower()
            if service_norm and service_norm in idx:
                matched.append(index)
                continue
            if tokens and all(token in idx for token in tokens):
                matched.append(index)
        return matched

    async def _match_service_indices_tool(self, service_name: str) -> Dict[str, Any]:
        try:
            matched = await self._match_service_indices(service_name)
            return self._tool_text(
                {
                    "provider": "elasticsearch",
                    "service_name": service_name,
                    "matched_indices": matched,
                    "count": len(matched),
                }
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in {401, 403}:
                return {"type": "text", "text": "Elasticsearch authentication failed. Verify ES credentials/API key."}
            return {"type": "text", "text": f"Elasticsearch index match failed ({code}): {exc.response.text}"}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"Elasticsearch index match failed: {exc}"}

    async def _get_mapping(self, index_name: str) -> Dict[str, Any]:
        return await self._request("GET", f"/{index_name}/_mapping")

    async def _get_mapping_tool(self, index_name: str) -> Dict[str, Any]:
        try:
            mapping = await self._get_mapping(index_name)
            return self._tool_text(
                {
                    "provider": "elasticsearch",
                    "index_name": index_name,
                    "mapping": mapping,
                }
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in {401, 403}:
                return {"type": "text", "text": "Elasticsearch authentication failed. Verify ES credentials/API key."}
            if code == 404:
                return {"type": "text", "text": f"Elasticsearch index not found: {index_name}"}
            return {"type": "text", "text": f"Elasticsearch get mapping failed ({code}): {exc.response.text}"}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"Elasticsearch get mapping failed: {exc}"}

    def _flatten_mapping_fields(self, node: Dict[str, Any], prefix: str = "") -> Dict[str, str]:
        fields: Dict[str, str] = {}
        props = node.get("properties", {}) if isinstance(node, dict) else {}
        if not isinstance(props, dict):
            return fields
        for key, value in props.items():
            if not isinstance(value, dict):
                continue
            field_name = f"{prefix}.{key}" if prefix else key
            field_type = str(value.get("type", "object"))
            fields[field_name] = field_type
            fields.update(self._flatten_mapping_fields(value, field_name))
        return fields

    def _pick_field(self, fields: Dict[str, str], candidates: Tuple[str, ...], preferred_types: Tuple[str, ...]) -> Optional[str]:
        for candidate in candidates:
            if candidate in fields and (not preferred_types or fields[candidate] in preferred_types):
                return candidate
        if preferred_types:
            for field_name, field_type in fields.items():
                if field_type in preferred_types:
                    return field_name
        for candidate in candidates:
            for field_name in fields:
                if field_name.lower().endswith(candidate.lower()):
                    return field_name
        return None

    async def _get_relevant_fields_tool(self, index_name: str) -> Dict[str, Any]:
        try:
            mapping = await self._get_mapping(index_name)
            root = mapping.get(index_name, {}).get("mappings", {})
            fields = self._flatten_mapping_fields(root)
            timestamp_field = self._pick_field(fields, self.TIMESTAMP_CANDIDATES, ("date", "date_nanos", "long"))
            source_field = self._pick_field(fields, self.SOURCE_CANDIDATES, ("keyword", "text", "wildcard"))
            trace_field = self._pick_field(fields, self.TRACE_CANDIDATES, ("keyword", "text"))
            log_url_field = self._pick_field(fields, self.LOG_URL_CANDIDATES, ("keyword", "text"))
            message_field = self._pick_field(fields, self.MESSAGE_CANDIDATES, ("text", "keyword"))
            return self._tool_text(
                {
                    "provider": "elasticsearch",
                    "index_name": index_name,
                    "relevant_fields": {
                        "timestamp": timestamp_field,
                        "source": source_field,
                        "traceId": trace_field,
                        "logUrl": log_url_field,
                        "message": message_field,
                    },
                    "field_count": len(fields),
                }
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in {401, 403}:
                return {"type": "text", "text": "Elasticsearch authentication failed. Verify ES credentials/API key."}
            if code == 404:
                return {"type": "text", "text": f"Elasticsearch index not found: {index_name}"}
            return {"type": "text", "text": f"Elasticsearch relevant fields lookup failed ({code}): {exc.response.text}"}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"Elasticsearch relevant fields lookup failed: {exc}"}

    @staticmethod
    def _get_nested(source: Dict[str, Any], field_path: Optional[str]) -> Any:
        if not field_path:
            return None
        value: Any = source
        for part in field_path.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
            if value is None:
                return None
        return value

    async def _fetch_service_logs(self, service_name: str, lookback_minutes: float = 60) -> Dict[str, Any]:
        try:
            matched_indices = await self._match_service_indices(service_name)
            if not matched_indices:
                return {
                    "type": "text",
                    "text": f"No Elasticsearch indices matched service '{service_name}'.",
                }

            mapping = await self._get_mapping(matched_indices[0])
            root = mapping.get(matched_indices[0], {}).get("mappings", {})
            fields = self._flatten_mapping_fields(root)

            timestamp_field = self._pick_field(fields, self.TIMESTAMP_CANDIDATES, ("date", "date_nanos", "long"))
            source_field = self._pick_field(fields, self.SOURCE_CANDIDATES, ("keyword", "text", "wildcard"))
            trace_field = self._pick_field(fields, self.TRACE_CANDIDATES, ("keyword", "text"))
            log_url_field = self._pick_field(fields, self.LOG_URL_CANDIDATES, ("keyword", "text"))
            message_field = self._pick_field(fields, self.MESSAGE_CANDIDATES, ("text", "keyword"))

            if not timestamp_field:
                return {
                    "type": "text",
                    "text": f"Could not determine timestamp field for index '{matched_indices[0]}'. Use elasticsearch_get_mapping.",
                }
            if not source_field:
                return {
                    "type": "text",
                    "text": f"Could not determine source field for index '{matched_indices[0]}'. Use elasticsearch_get_mapping.",
                }

            try:
                lookback_sec = max(int(float(lookback_minutes) * 60), 60)
            except (TypeError, ValueError):
                lookback_sec = 3600

            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(seconds=lookback_sec)
            end_iso = end_time.isoformat()
            start_iso = start_time.isoformat()

            body = {
                "size": settings.ELASTICSEARCH_MCP_MAX_HITS,
                "query": {
                    "bool": {
                        "must": [
                            {
                                "match": {
                                    source_field: {
                                        "query": service_name,
                                        "operator": "and",
                                    }
                                }
                            }
                        ],
                        "filter": [
                            {
                                "range": {
                                    timestamp_field: {
                                        "gte": start_iso,
                                        "lte": end_iso,
                                        "format": "strict_date_optional_time||epoch_millis||epoch_second",
                                    }
                                }
                            }
                        ],
                    }
                },
                "sort": [{timestamp_field: {"order": "desc"}}],
            }

            index_target = ",".join(matched_indices[:20])
            data = await self._request("POST", f"/{index_target}/_search", body=body)

            hits = data.get("hits", {}).get("hits", []) if isinstance(data, dict) else []
            logs: List[Dict[str, Any]] = []
            lines: List[str] = []
            for hit in hits:
                src = hit.get("_source", {}) if isinstance(hit, dict) else {}
                if not isinstance(src, dict):
                    continue
                ts = self._get_nested(src, timestamp_field)
                source_val = self._get_nested(src, source_field)
                trace_val = self._get_nested(src, trace_field)
                url_val = self._get_nested(src, log_url_field)
                msg_val = self._get_nested(src, message_field) if message_field else src.get("message")
                log_entry = {
                    "timestamp": ts,
                    "source": source_val or service_name,
                    "traceId": trace_val,
                    "logUrl": url_val,
                    "message": msg_val or "",
                }
                logs.append(log_entry)
                lines.append(
                    f"{log_entry['timestamp']} | source={log_entry['source']} | "
                    f"traceId={log_entry.get('traceId')} | logUrl={log_entry.get('logUrl')}"
                )

            summary = "\n".join(lines[:50]) if lines else f"No logs found for '{service_name}' in selected indices."
            return self._tool_text(
                {
                    "provider": "elasticsearch",
                    "service_name": service_name,
                    "index_target": index_target,
                    "matched_indices": matched_indices,
                    "timestamp_field": timestamp_field,
                    "source_field": source_field,
                    "trace_field": trace_field,
                    "log_url_field": log_url_field,
                    "result_count": len(logs),
                    "summary": summary,
                    "logs": logs,
                }
            )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in {401, 403}:
                return {"type": "text", "text": "Elasticsearch authentication failed. Verify ES credentials/API key."}
            if code == 404:
                return {"type": "text", "text": "Elasticsearch index not found while fetching logs."}
            return {"type": "text", "text": f"Elasticsearch log query failed ({code}): {exc.response.text}"}
        except Exception as exc:  # noqa: BLE001
            return {"type": "text", "text": f"Elasticsearch log query failed: {exc}"}

    async def cleanup(self) -> None:
        if self._http_client:
            await self._http_client.aclose()
