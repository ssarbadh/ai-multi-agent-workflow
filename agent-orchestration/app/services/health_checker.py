"""Service health checker for backend services.

Checks health of all backend services at startup and periodically.
"""

import logging
import asyncio
from typing import Dict, Any
from datetime import datetime

from app.services.context_client import context_client
from app.services.rag_client import rag_client
from app.services.mcp_client import mcp_client
from app.services.observability_client import observability_client

logger = logging.getLogger(__name__)


class HealthChecker:
    """
    Health checker for backend services.
    
    Checks health of:
    - Context Management service
    - RAG service
    - MCP service
    - Observability service
    """
    
    def __init__(self):
        self._service_status: Dict[str, Dict[str, Any]] = {}
        self._last_check: Dict[str, datetime] = {}
        self._check_interval = 60  # seconds
    
    async def check_all_services(self) -> Dict[str, Dict[str, Any]]:
        """
        Check health of all backend services.
        
        Returns:
            Dict with service status for each service
        """
        logger.info("Checking health of all backend services...")
        
        services = {
            "context_management": self._check_context_management,
            "rag": self._check_rag,
            "mcp": self._check_mcp,
            "observability": self._check_observability
        }
        
        results = {}
        
        for service_name, check_func in services.items():
            try:
                status = await check_func()
                results[service_name] = status
                self._service_status[service_name] = status
                self._last_check[service_name] = datetime.utcnow()
                
                if status["healthy"]:
                    logger.info(f"✓ {service_name} service is healthy")
                else:
                    logger.warning(f"✗ {service_name} service is unavailable: {status.get('error', 'Unknown error')}")
            except Exception as e:
                logger.error(f"✗ {service_name} health check failed: {e}")
                results[service_name] = {
                    "healthy": False,
                    "error": str(e),
                    "checked_at": datetime.utcnow().isoformat()
                }
        
        return results
    
    async def _check_context_management(self) -> Dict[str, Any]:
        """Check Context Management service health."""
        try:
            # Try to get a prompt (lightweight operation)
            result = await context_client.get_prompt("test", version="latest")
            
            return {
                "healthy": True,
                "checked_at": datetime.utcnow().isoformat(),
                "response_time_ms": 0  # Could measure actual time
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "checked_at": datetime.utcnow().isoformat()
            }
    
    async def _check_rag(self) -> Dict[str, Any]:
        """Check RAG service health."""
        try:
            healthy = await rag_client.health_check()
            
            return {
                "healthy": healthy,
                "checked_at": datetime.utcnow().isoformat(),
                "response_time_ms": 0
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "checked_at": datetime.utcnow().isoformat()
            }
    
    async def _check_mcp(self) -> Dict[str, Any]:
        """Check MCP service health."""
        try:
            healthy = await mcp_client.health_check()
            
            return {
                "healthy": healthy,
                "checked_at": datetime.utcnow().isoformat(),
                "response_time_ms": 0
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "checked_at": datetime.utcnow().isoformat()
            }
    
    async def _check_observability(self) -> Dict[str, Any]:
        """Check Observability service health."""
        try:
            healthy = await observability_client.health_check()
            
            return {
                "healthy": healthy,
                "checked_at": datetime.utcnow().isoformat(),
                "response_time_ms": 0
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
                "checked_at": datetime.utcnow().isoformat()
            }
    
    def get_service_status(self, service_name: str) -> Dict[str, Any]:
        """Get cached status of a service."""
        return self._service_status.get(service_name, {
            "healthy": False,
            "error": "Status not available",
            "checked_at": None
        })
    
    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get cached status of all services."""
        return self._service_status.copy()
    
    async def start_periodic_checks(self):
        """Start periodic health checks in background."""
        logger.info(f"Starting periodic health checks (interval: {self._check_interval}s)")
        
        while True:
            try:
                await asyncio.sleep(self._check_interval)
                await self.check_all_services()
            except asyncio.CancelledError:
                logger.info("Periodic health checks cancelled")
                break
            except Exception as e:
                logger.error(f"Error in periodic health check: {e}")


# Global health checker instance
health_checker = HealthChecker()
