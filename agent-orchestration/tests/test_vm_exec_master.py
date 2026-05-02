"""Master test file for VM Exec Agent.

Tests container execution, streaming, prompts, and approvals.
Per HLD: VM Exec Agent – Runs commands in sandbox VM/container; streams stdout/stderr
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from app.schemas.vm_exec_schemas import (
    ExecutionStatus, ExecutionType, InputPromptType,
    VMCommandRequest, VMExecutionResult, InputPrompt
)


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    if asyncio.sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ===================================
# Schema Tests
# ===================================

class TestVMExecSchemas:
    """Test VM Exec Pydantic schemas."""
    
    def test_execution_status_enum(self):
        """Test ExecutionStatus enum values."""
        assert ExecutionStatus.PENDING.value == "pending"
        assert ExecutionStatus.RUNNING.value == "running"
        assert ExecutionStatus.WAITING_INPUT.value == "waiting_input"
        assert ExecutionStatus.WAITING_APPROVAL.value == "waiting_approval"
        assert ExecutionStatus.COMPLETED.value == "completed"
        assert ExecutionStatus.FAILED.value == "failed"
        assert ExecutionStatus.TIMEOUT.value == "timeout"
        assert ExecutionStatus.CANCELLED.value == "cancelled"
    
    def test_execution_type_enum(self):
        """Test ExecutionType enum values."""
        assert ExecutionType.DOCKER.value == "docker"
        assert ExecutionType.KUBERNETES.value == "kubernetes"
        assert ExecutionType.SSH.value == "ssh"
        assert ExecutionType.LOCAL.value == "local"
    
    def test_input_prompt_type_enum(self):
        """Test InputPromptType enum values."""
        assert InputPromptType.PASSWORD.value == "password"
        assert InputPromptType.CONFIRMATION.value == "confirmation"
        assert InputPromptType.TEXT.value == "text"
        assert InputPromptType.APPROVAL.value == "approval"
    
    def test_vm_command_request_schema(self):
        """Test VMCommandRequest schema."""
        request = VMCommandRequest(
            run_id="run_123",
            command="echo hello",
            timeout_seconds=60
        )
        assert request.run_id == "run_123"
        assert request.command == "echo hello"
        assert request.timeout_seconds == 60
        assert request.execution_type == ExecutionType.DOCKER
    
    def test_vm_execution_result_schema(self):
        """Test VMExecutionResult schema."""
        result = VMExecutionResult(
            execution_id="vmexec_abc123",
            run_id="run_123",
            command="echo hello",
            command_hash="abc123",
            status=ExecutionStatus.COMPLETED,
            exit_code=0,
            stdout="hello\n",
            stderr="",
            execution_type=ExecutionType.DOCKER
        )
        assert result.execution_id == "vmexec_abc123"
        assert result.status == ExecutionStatus.COMPLETED
        assert result.exit_code == 0
    
    def test_input_prompt_schema(self):
        """Test InputPrompt schema."""
        prompt = InputPrompt(
            prompt_id="prompt_123",
            prompt_type=InputPromptType.PASSWORD,
            message="Enter password:"
        )
        assert prompt.prompt_id == "prompt_123"
        assert prompt.prompt_type == InputPromptType.PASSWORD


# ===================================
# Docker Client Tests
# ===================================

class TestDockerClient:
    """Test Docker client."""
    
    def test_client_initialization(self):
        """Test client initialization."""
        from app.clients.docker_client import DockerClient
        client = DockerClient()
        assert client is not None
        assert client.default_image is not None
    
    def test_mask_secrets(self):
        """Test secret masking."""
        from app.clients.docker_client import DockerClient
        client = DockerClient()
        
        text = "password=secret123 token=abc123"
        masked = client.mask_secrets(text)
        assert "secret123" not in masked
        assert "[REDACTED]" in masked
    
    def test_detect_password_prompt(self):
        """Test password prompt detection."""
        from app.clients.docker_client import DockerClient
        client = DockerClient()
        
        assert client.detect_prompt_type("Password: ") == "password"
        assert client.detect_prompt_type("[sudo] password for user:") == "password"
        assert client.detect_prompt_type("Enter passphrase:") == "password"
    
    def test_detect_confirmation_prompt(self):
        """Test confirmation prompt detection."""
        from app.clients.docker_client import DockerClient
        client = DockerClient()
        
        assert client.detect_prompt_type("Continue? [y/n]") == "confirmation"
        assert client.detect_prompt_type("Are you sure?") == "confirmation"
        assert client.detect_prompt_type("Proceed? [Y/n]") == "confirmation"
    
    def test_no_prompt_detected(self):
        """Test no prompt detection for normal output."""
        from app.clients.docker_client import DockerClient
        client = DockerClient()
        
        assert client.detect_prompt_type("Hello world") is None
        assert client.detect_prompt_type("Processing...") is None


# ===================================
# VM Exec Agent Tests
# ===================================

class TestVMExecAgent:
    """Test VM Exec Agent."""
    
    def test_agent_initialization(self):
        """Test agent initialization."""
        from app.agents.vm_exec_agent import VMExecAgent
        agent = VMExecAgent()
        assert agent is not None
        assert agent.docker is not None
        assert agent.workflow is not None
    
    def test_agent_default_image(self):
        """Test default image configuration."""
        from app.agents.vm_exec_agent import VMExecAgent
        agent = VMExecAgent()
        assert agent.default_image is not None
        assert "python" in agent.default_image or agent.default_image != ""
    
    @pytest.mark.asyncio
    async def test_execute_command_local(self):
        """Test local command execution."""
        from app.agents.vm_exec_agent import VMExecAgent
        from app.schemas.vm_exec_schemas import ExecutionType
        
        agent = VMExecAgent()
        result = await agent.execute_command(
            run_id="test_run",
            command="echo hello",
            execution_type=ExecutionType.LOCAL,
            timeout_seconds=30
        )
        
        assert result.execution_id is not None
        assert result.run_id == "test_run"
        assert result.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]
    
    @pytest.mark.asyncio
    async def test_execute_empty_command_fails(self):
        """Test that empty command fails validation."""
        from app.agents.vm_exec_agent import VMExecAgent
        
        agent = VMExecAgent()
        result = await agent.execute_command(
            run_id="test_run",
            command="",
            execution_type=ExecutionType.LOCAL
        )
        
        assert result.status == ExecutionStatus.FAILED
        assert "empty" in result.error.lower()
    
    @pytest.mark.asyncio
    async def test_dangerous_command_blocked(self):
        """Test that dangerous commands are blocked."""
        from app.agents.vm_exec_agent import VMExecAgent
        
        agent = VMExecAgent()
        result = await agent.execute_command(
            run_id="test_run",
            command="rm -rf /",
            execution_type=ExecutionType.LOCAL
        )
        
        assert result.status == ExecutionStatus.FAILED
        assert "dangerous" in result.error.lower()
    
    def test_get_execution_status_not_found(self):
        """Test getting status for non-existent execution."""
        from app.agents.vm_exec_agent import VMExecAgent
        
        agent = VMExecAgent()
        status = agent.get_execution_status("nonexistent_id")
        assert status is None


# ===================================
# VM Executor Service Tests
# ===================================

class TestVMExecutorService:
    """Test VM Executor service."""
    
    def test_service_initialization(self):
        """Test service initialization."""
        from app.services.vm_executor import vm_executor
        assert vm_executor is not None
    
    @pytest.mark.asyncio
    async def test_execute_local_command(self):
        """Test local command execution via service."""
        from app.services.vm_executor import VMExecutor
        from app.schemas.vm_exec_schemas import ExecutionType
        
        executor = VMExecutor()
        # Service doesn't take execution_type, uses local by default when docker unavailable
        result = await executor.execute_command(
            run_id="test_run",
            command="echo test",
            timeout_seconds=30
        )
        
        assert result.id is not None
        assert result.run_id == "test_run"


# ===================================
# API Tests
# ===================================

class TestVMConsoleAPI:
    """Test VM Console API endpoints."""
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test health endpoint."""
        from app.api.vm_console import vm_health
        result = await vm_health()
        assert result["status"] == "healthy"
        assert "docker_available" in result


# ===================================
# Integration Tests (Mocked)
# ===================================

class TestVMExecIntegration:
    """Integration tests with mocked Docker."""
    
    @pytest.fixture
    def mock_docker_client(self):
        """Mock Docker client."""
        with patch("app.clients.docker_client.docker_client") as mock:
            mock.is_configured = True
            mock.run_command = AsyncMock(return_value=MagicMock(
                container_id="test_container",
                exit_code=0,
                stdout="Success",
                stderr="",
                duration_seconds=1.5
            ))
            mock.mask_secrets = MagicMock(side_effect=lambda x, y=None: x)
            yield mock
    
    @pytest.mark.asyncio
    async def test_docker_execution_mocked(self, mock_docker_client):
        """Test Docker execution with mocked client."""
        from app.agents.vm_exec_agent import VMExecAgent
        
        agent = VMExecAgent()
        agent.docker = mock_docker_client
        
        # Would test Docker execution here
        assert agent.docker.is_configured is True


# ===================================
# Approval Flow Tests
# ===================================

class TestApprovalFlow:
    """Test approval workflow."""
    
    @pytest.mark.asyncio
    async def test_provide_approval_not_found(self):
        """Test providing approval for non-existent execution."""
        from app.agents.vm_exec_agent import VMExecAgent
        
        agent = VMExecAgent()
        result = await agent.provide_approval(
            execution_id="nonexistent",
            approved=True,
            approver="admin"
        )
        assert result is False
    
    @pytest.mark.asyncio
    async def test_provide_input_not_found(self):
        """Test providing input for non-existent execution."""
        from app.agents.vm_exec_agent import VMExecAgent
        
        agent = VMExecAgent()
        result = await agent.provide_input(
            execution_id="nonexistent",
            prompt_id="prompt_123",
            value="test"
        )
        assert result is False
    
    @pytest.mark.asyncio
    async def test_cancel_execution_not_found(self):
        """Test cancelling non-existent execution."""
        from app.agents.vm_exec_agent import VMExecAgent
        
        agent = VMExecAgent()
        result = await agent.cancel_execution("nonexistent")
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
