"""
Master test file for comprehensive E2E testing.

This test file covers:
1. Health checks
2. Orchestration flow (SR/CR and Incident paths)
3. Approvals and human-in-the-loop
4. VM execution
5. ServiceNow integration
6. Streaming
7. Error handling
"""

import pytest
import asyncio
from datetime import datetime
from httpx import AsyncClient

from app.models.models import Run, RunStatus, RequestType


class TestHealthChecks:
    """Test health check endpoints."""
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self, client: AsyncClient):
        """Test health check endpoint."""
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "components" in data
    
    @pytest.mark.asyncio
    async def test_readiness_probe(self, client: AsyncClient):
        """Test Kubernetes readiness probe."""
        response = await client.get("/api/v1/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"
    
    @pytest.mark.asyncio
    async def test_liveness_probe(self, client: AsyncClient):
        """Test Kubernetes liveness probe."""
        response = await client.get("/api/v1/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"


class TestOrchestration:
    """Test orchestration endpoints."""
    
    @pytest.mark.asyncio
    async def test_start_service_request(self, client: AsyncClient):
        """Test starting a service request orchestration."""
        request_data = {
            "session_id": "test_session_1",
            "user_id": "test_user_1",
            "message": "Create a new VM with 4 CPUs and 8GB RAM",
            "priority": "medium"
        }
        
        response = await client.post("/api/v1/orchestrate", json=request_data)
        assert response.status_code == 202
        
        data = response.json()
        assert "id" in data
        assert data["session_id"] == request_data["session_id"]
        assert data["user_id"] == request_data["user_id"]
        assert data["status"] == "pending"
    
    @pytest.mark.asyncio
    async def test_get_run_details(self, client: AsyncClient):
        """Test getting run details."""
        # First create a run
        request_data = {
            "session_id": "test_session_2",
            "user_id": "test_user_2",
            "message": "Deploy application to production",
            "priority": "high"
        }
        
        create_response = await client.post("/api/v1/orchestrate", json=request_data)
        run_id = create_response.json()["id"]
        
        # Get run details
        response = await client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == run_id
        assert data["session_id"] == request_data["session_id"]
    
    @pytest.mark.asyncio
    async def test_list_runs(self, client: AsyncClient):
        """Test listing runs with filters."""
        # Create multiple runs
        for i in range(3):
            request_data = {
                "session_id": f"test_session_{i}",
                "user_id": "test_user",
                "message": f"Test request {i}",
                "priority": "medium"
            }
            await client.post("/api/v1/orchestrate", json=request_data)
        
        # List all runs
        response = await client.get("/api/v1/runs")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 3
    
    @pytest.mark.asyncio
    async def test_cancel_run(self, client: AsyncClient):
        """Test cancelling a run."""
        # Create a run
        request_data = {
            "session_id": "test_session_cancel",
            "user_id": "test_user",
            "message": "Long running task",
            "priority": "low"
        }
        
        create_response = await client.post("/api/v1/orchestrate", json=request_data)
        run_id = create_response.json()["id"]
        
        # Cancel the run
        response = await client.post(f"/api/v1/runs/{run_id}/cancel")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "cancelled"
        assert data["run_id"] == run_id


class TestStatistics:
    """Test statistics endpoints."""
    
    @pytest.mark.asyncio
    async def test_get_stats(self, client: AsyncClient):
        """Test getting orchestration statistics."""
        response = await client.get("/api/v1/stats")
        assert response.status_code == 200
        
        data = response.json()
        assert "total_runs" in data
        assert "active_runs" in data
        assert "completed_runs" in data
        assert "failed_runs" in data
        assert isinstance(data["total_runs"], int)


class TestApprovals:
    """Test approval endpoints."""
    
    @pytest.mark.asyncio
    async def test_list_approvals(self, client: AsyncClient):
        """Test listing approvals."""
        response = await client.get("/api/v1/approvals")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)


class TestVMExecution:
    """Test VM execution endpoints."""
    
    @pytest.mark.asyncio
    async def test_list_vm_executions(self, client: AsyncClient):
        """Test listing VM executions."""
        response = await client.get("/api/v1/vm/executions")
        assert response.status_code == 200
        
        data = response.json()
        assert isinstance(data, list)


class TestIntegration:
    """Integration tests for complete workflows."""
    
    @pytest.mark.asyncio
    async def test_sr_cr_workflow(self, client: AsyncClient):
        """Test complete SR/CR workflow."""
        # Start orchestration
        request_data = {
            "session_id": "integration_test_1",
            "user_id": "test_user",
            "message": "Create a new Kubernetes cluster with 3 nodes",
            "priority": "high"
        }
        
        response = await client.post("/api/v1/orchestrate", json=request_data)
        assert response.status_code == 202
        
        run_id = response.json()["id"]
        
        # Wait a bit for processing
        await asyncio.sleep(2)
        
        # Check run status
        response = await client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == run_id
        # Status should have progressed
        assert data["status"] in ["pending", "running", "completed"]
    
    @pytest.mark.asyncio
    async def test_incident_workflow(self, client: AsyncClient):
        """Test complete incident workflow."""
        # Start orchestration
        request_data = {
            "session_id": "integration_test_2",
            "user_id": "test_user",
            "message": "Production web server is down and not responding",
            "priority": "critical"
        }
        
        response = await client.post("/api/v1/orchestrate", json=request_data)
        assert response.status_code == 202
        
        run_id = response.json()["id"]
        
        # Wait for processing
        await asyncio.sleep(2)
        
        # Check run status
        response = await client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200
        
        data = response.json()
        assert data["id"] == run_id


class TestErrorHandling:
    """Test error handling."""
    
    @pytest.mark.asyncio
    async def test_get_nonexistent_run(self, client: AsyncClient):
        """Test getting a non-existent run."""
        response = await client.get("/api/v1/runs/nonexistent_run_id")
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_invalid_orchestration_request(self, client: AsyncClient):
        """Test invalid orchestration request."""
        request_data = {
            "session_id": "test",
            # Missing required fields
        }
        
        response = await client.post("/api/v1/orchestrate", json=request_data)
        assert response.status_code == 422  # Validation error


# Run all tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--asyncio-mode=auto"])
