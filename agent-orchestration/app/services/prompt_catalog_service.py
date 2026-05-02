"""Versioned prompt catalog loader for agent workflows."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


class _SafeDict(dict):
    """Safe formatter dict that preserves unknown placeholders."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class PromptCatalogService:
    """Loads prompt templates from catalog and renders versioned prompts."""

    def __init__(self, catalog_path: str) -> None:
        self.catalog_path = Path(catalog_path)
        self._catalog: Dict[str, Any] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return

        if not self.catalog_path.exists():
            logger.warning("Prompt catalog not found: %s", self.catalog_path)
            self._catalog = {}
            self._loaded = True
            return

        with self.catalog_path.open("r", encoding="utf-8") as handle:
            parsed = yaml.safe_load(handle) or {}

        self._catalog = parsed.get("prompts", {})
        self._loaded = True
        logger.info("Loaded prompt catalog with %d entries", len(self._catalog))

    def reload(self) -> Dict[str, Any]:
        """Force reload prompt catalog from disk."""
        self._loaded = False
        self._catalog = {}
        self._load()
        return {
            "status": "reloaded",
            "catalog_path": str(self.catalog_path),
            "prompt_count": len(self._catalog),
        }

    def prompt_count(self) -> int:
        """Return number of prompt definitions in catalog."""
        self._load()
        return len(self._catalog)

    def get_prompt_definition(self, prompt_key: str) -> Dict[str, Any]:
        self._load()
        prompt_def = self._catalog.get(prompt_key)
        if not prompt_def:
            raise KeyError(f"Prompt key not found in catalog: {prompt_key}")
        return prompt_def

    def render(self, prompt_key: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        prompt_def = self.get_prompt_definition(prompt_key)
        base_dir = self.catalog_path.parent

        system_template_path = base_dir / prompt_def["system_template"]
        user_template_path = base_dir / prompt_def["user_template"]

        system_template = system_template_path.read_text(encoding="utf-8")
        user_template = user_template_path.read_text(encoding="utf-8")

        safe_vars = _SafeDict({k: str(v) for k, v in variables.items()})
        # Use token replacement instead of str.format_map so raw JSON braces
        # in prompt templates don't trigger format parsing errors.
        system_rendered = self._render_template(system_template, safe_vars)
        user_rendered = self._render_template(user_template, safe_vars)

        return {
            "id": prompt_def.get("id", prompt_key),
            "version": prompt_def.get("version", "0.0.0"),
            "owner": prompt_def.get("owner", "unknown"),
            "system": system_rendered,
            "user": user_rendered,
        }

    @staticmethod
    def _render_template(template: str, variables: Dict[str, str]) -> str:
        """Replace {var} tokens while preserving unrelated braces."""
        pattern = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
        return pattern.sub(lambda m: variables.get(m.group(1), m.group(0)), template)

