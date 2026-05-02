"""Logs processor - parses logs and extracts error patterns.

Supports Quickwit, Elasticsearch, or simulated input.
Follows MCP_CONTEXT_CONTRACTS structure for log sources.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import logger


class LogsProcessor:
    """Parses logs and extracts error pattern signatures (normalized for grouping)."""

    # Patterns to normalize in error messages (replace with placeholder)
    NORMALIZE_PATTERNS = [
        (re.compile(r"\b\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}[\.\d]*[Z\s]?"), "TIMESTAMP"),
        (re.compile(r"\b\d{10,}\b"), "NUM"),
        (re.compile(r"0x[0-9a-fA-F]+"), "HEX"),
        (re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"), "UUID"),
        (re.compile(r"/[a-zA-Z0-9/_-]+"), "PATH"),
        (re.compile(r"[\w.-]+\.(com|io|org|net)"), "DOMAIN"),
    ]
    DEPENDENCY_PATTERNS = [
        (re.compile(r"(?P<name>[\w.-]+\.elb\.amazonaws\.com)", re.IGNORECASE), "ExternalService", "AWS_ELB"),
        (re.compile(r"(?P<name>[\w.-]+\.rds\.amazonaws\.com)", re.IGNORECASE), "Database", "AWS_RDS"),
        (re.compile(r"(?P<name>[\w.-]+\.cache\.amazonaws\.com)", re.IGNORECASE), "Database", "AWS_CACHE"),
        (re.compile(r"\brabbitmq\b|\bamqp\b", re.IGNORECASE), "ExternalService", "RabbitMQ"),
        (re.compile(r"\bredis\b", re.IGNORECASE), "Database", "Redis"),
        (re.compile(r"\bmongo(?:db)?\b", re.IGNORECASE), "Database", "MongoDB"),
        (re.compile(r"\bpostgres(?:ql)?\b", re.IGNORECASE), "Database", "PostgreSQL"),
    ]

    @staticmethod
    def _extract_product(service_name: str) -> str:
        return (service_name or "").split("-", 1)[0].lower() or "unknown"

    @staticmethod
    def signature_from_message(msg: str) -> str:
        """Normalize log message to a stable signature for grouping."""
        if not msg or not isinstance(msg, str):
            return "unknown"
        s = msg.strip()
        for pat, placeholder in LogsProcessor.NORMALIZE_PATTERNS:
            s = pat.sub(placeholder, s)
        s = re.sub(r"\s+", " ", s)[:400]
        return hashlib.sha256(s.encode()).hexdigest()[:32]

    @staticmethod
    def signature_readable(msg: str) -> str:
        """Human-readable signature (first 120 chars, normalized)."""
        if not msg or not isinstance(msg, str):
            return "unknown"
        s = msg.strip()
        for pat, placeholder in LogsProcessor.NORMALIZE_PATTERNS:
            s = pat.sub(placeholder, s)
        s = re.sub(r"\s+", " ", s)
        return s[:120] if len(s) > 120 else s

    def extract_error_patterns(
        self,
        logs: List[Dict[str, Any]],
        source_field: str = "message",
        min_count: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Extract error patterns from log entries.
        Returns list of {signature, count, sample} - signature is readable for graph display.
        """
        counter: Counter[str] = {}
        samples: Dict[str, str] = {}
        for entry in logs:
            if not isinstance(entry, dict):
                continue
            msg = entry.get(source_field) or entry.get("message") or entry.get("log") or str(entry)
            sig_hash = self.signature_from_message(str(msg))
            readable = self.signature_readable(str(msg))
            counter[sig_hash] = counter.get(sig_hash, 0) + 1
            if sig_hash not in samples:
                samples[sig_hash] = readable
        patterns = [
            {"signature": samples.get(sig, sig), "count": c}
            for sig, c in counter.items()
            if c >= min_count
        ]
        return sorted(patterns, key=lambda x: -x["count"])[:50]

    def parse_quickwit_result(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Quickwit search result into log entries."""
        logs: List[Dict[str, Any]] = []
        hits = result.get("hits", []) or result.get("result", {}).get("hits", [])
        if not isinstance(hits, list):
            return logs
        for h in hits:
            src = h.get("_source") or h.get("source") or h
            if isinstance(src, dict):
                logs.append(src)
        return logs

    def parse_elasticsearch_result(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Parse Elasticsearch search result into log entries."""
        logs: List[Dict[str, Any]] = []
        hits = result.get("hits", {}).get("hits", []) if isinstance(result, dict) else []
        for h in hits:
            src = h.get("_source", {})
            if isinstance(src, dict):
                logs.append(src)
        return logs

    def get_logs_simulated(self, service_name: str, pod_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Simulate log entries for testing."""
        pod = pod_name or f"{service_name}-abc123"
        return [
            {"message": "ERROR: Connection timeout to database", "kubernetes.container_name": service_name, "kubernetes.pod_name": pod, "pod": pod},
            {"message": "ERROR: Connection timeout to database", "kubernetes.container_name": service_name, "kubernetes.pod_name": pod, "pod": pod},
            {"message": "java.lang.NullPointerException at com.example.Service.handle()", "kubernetes.container_name": service_name, "kubernetes.pod_name": pod, "pod": pod},
            {"message": "503 Service Unavailable", "kubernetes.container_name": service_name, "kubernetes.pod_name": pod, "pod": pod},
        ]

    def extract_dependencies_from_logs(
        self,
        logs: List[Dict[str, Any]],
        service_name: str,
    ) -> List[Dict[str, Any]]:
        """Extract external dependency signals from log lines for graph enrichment."""
        dependencies: Dict[str, Dict[str, Any]] = {}
        for entry in logs[:500]:
            if not isinstance(entry, dict):
                continue
            message = str(entry.get("message") or entry.get("log") or "")
            if not message:
                continue
            for pattern, node_label, dep_type in self.DEPENDENCY_PATTERNS:
                matches = list(pattern.finditer(message))
                if not matches:
                    continue
                for match in matches:
                    name = match.groupdict().get("name") or match.group(0)
                    key = f"{node_label}:{name.lower()}"
                    if key not in dependencies:
                        dependencies[key] = {
                            "service_name": service_name,
                            "dependency_name": name,
                            "dependency_label": node_label,
                            "dependency_type": dep_type,
                            "evidence": message[:300],
                        }
        return list(dependencies.values())[:100]
