"""LangSmith tracing for LangGraph runs and custom LLM client spans."""

from __future__ import annotations

import logging
import os

from app.core.config import settings

logger = logging.getLogger(__name__)


def configure_langsmith_from_settings() -> None:
    """
    Sync LangSmith / LangChain tracing env vars from application settings.

    LangGraph and LangSmith read LANGCHAIN_* from os.environ. Pydantic Settings
    can load the same variables from .env; we mirror enabled keys here so both
    the API process and one-off CLIs behave consistently.
    """
    if settings.LANGCHAIN_TRACING_V2:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        if settings.LANGCHAIN_API_KEY:
            os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
        if settings.LANGCHAIN_PROJECT:
            os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
        if settings.LANGCHAIN_ENDPOINT:
            os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
        logger.info(
            "LangSmith tracing enabled (project=%s)",
            settings.LANGCHAIN_PROJECT,
        )
        if not os.environ.get("LANGCHAIN_API_KEY"):
            logger.warning(
                "LANGCHAIN_TRACING_V2 is true but LANGCHAIN_API_KEY is not set; "
                "LangSmith runs may fail to upload."
            )
    else:
        # Do not strip LANGCHAIN_TRACING_V2 if the user set it only in the shell.
        if os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in ("1", "true"):
            logger.info("LangSmith tracing enabled via environment (LANGCHAIN_TRACING_V2).")
