"""
Integration tests for DevOps V5 complete workflow.

Tests:
- Intent detection (conversational vs DevOps)
- Conversational agent responses
- DevOps V5 workflow execution
- Local file operations
- Critic agent review
- VM Console streaming
- HITL approvals
- Workflow state persistence
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from app.services.intent_detector import intent_detector, Intent
from app.agents.conversational_agent import conversational_agent
from app.agents.devops_agent_v5 import devops_agent_v5
from app.services.local_file_manager import local_file_manager
from app.agents.critic_agent import critic_agent
from app.services.vm_console_streamer import vm_console_streamer, MessageType
from app.services.workflow_state_store import workflow_state_store


class TestIntentDetection:
    """Test intent detection service."""
    
    @pytest.mark.asyncio
    async def test_detect_conversational_intent(self):
        """Test detection of conversational messages."""
        messages = ["hi", "hello", "how are you", "what can you do", "help"]
        
        for message in messages:
            intent = await intent_detector.detect(message)
            assert intent == Intent.CONVERSATIONAL, f"Failed for: {message}"
    
    @pytest.mark.asyncio
    async def test_detect_devops_intent(self):
        """Test detection of DevOps messages."""
        messages = [
            "create a python flask app",
            "deploy nodejs application",
            "setup ci/cd pipeline",
            "build docker container",
            "create github repo"
        ]
        
        for message in messages:
            intent = await intent_detector.detect(message)
            assert intent == Intent.DEVOPS, f"Failed for: {message}"
    
    def test_extract_repo_info(self):
        """Test repository info extraction."""
        message = "create a repo called payment-api on branch feature/auth"
        
        info = intent_detector.extract_repo_info(message)
        
        assert info["repo_name"] == "payment-api"
        assert info["branch_name"] == "feature/auth"


class TestConversationalAgent:
    """Test conversational agent."""
    
    @pytest.mark.asyncio
    async def test_handle_greeting(self):
        """Test greeting response."""
        response = await conversational_agent.handle_conversation("hello")
        
        assert len(response) > 0
        assert any(word in response.lower() for word in ["hello", "hi", "aegisops"])
    
    @pytest.mark.asyncio
    async def test_handle_help_request(self):
        """Test help request response."""
        response = await conversational_agent.handle_conversation("what can you do")
        
        assert len(response) > 0
        assert any(word in response.lower() for word in ["devops", "automation", "deploy"])
    
    @pytest.mark.asyncio
    async def test_context_awareness(self):
        """Test context-aware responses."""
        context = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello! How can I help?"}
        ]
        
        response = await conversational_agent.handle_conversation(
            "what was my last message",
            context=context
        )
        
        assert len(response) > 0


class TestLocalFileManager:
    """Test local file manager."""
    
    def test_get_repo_path(self):
        """Test repository path generation."""
        path = local_file_manager.get_repo_path("test-repo")
        
        assert "test-repo" in str(path)
        assert "C:\\New Drive\\Testing\\Repo_directory" in str(path)
    
    def test_base_directory(self):
        """Test fixed base directory."""
        base_dir = local_file_manager.get_base_directory()
        
        assert base_dir == r"C:\New Drive\Testing\Repo_directory"


class TestCriticAgent:
    """Test critic agent."""
    
    @pytest.mark.asyncio
    async def test_review_single_file(self):
        """Test single file review."""
        file_content = """
def hello():
    print("Hello World")
"""
        
        review = await critic_agent._review_single_file(
            file_path="app.py",
            content=file_content,
            user_prompt="create a hello world app",
            metadata={"language": "Python"}
        )
        
        assert review.file_path == "app.py"
        assert 1 <= review.score <= 10
        assert isinstance(review.issues, list)
        assert isinstance(review.suggestions, list)
    
    @pytest.mark.asyncio
    @patch('app.agents.critic_agent.critic_agent._review_single_file')
    @patch('app.agents.critic_agent.critic_agent._improve_single_file')
    async def test_review_and_improve(self, mock_improve, mock_review):
        """Test iterative review and improvement."""
        # Mock review results
        mock_review.return_value = Mock(
            file_path="app.py",
            score=7,
            issues=["Missing docstring"],
            suggestions=["Add type hints"],
            approved=False
        )
        
        # Mock improvement
        mock_improve.return_value = "# Improved content"
        
        files = {"app.py": "# Original content"}
        
        improved_files, history = await critic_agent.review_and_improve(
            files=files,
            user_prompt="create app",
            metadata={"language": "Python"},
            max_iterations=2
        )
        
        assert len(history) > 0
        assert "app.py" in improved_files


class TestVMConsoleStreamer:
    """Test VM Console streamer."""
    
    @pytest.mark.asyncio
    @patch('app.services.vm_console_streamer.redis_client')
    async def test_stream_message(self, mock_redis):
        """Test message streaming."""
        mock_redis.publish = AsyncMock()
        
        await vm_console_streamer.stream_message(
            run_id="test-run",
            message="Test message",
            message_type=MessageType.INFO
        )
        
        mock_redis.publish.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('app.services.vm_console_streamer.redis_client')
    async def test_stream_success(self, mock_redis):
        """Test success message streaming."""
        mock_redis.publish = AsyncMock()
        
        await vm_console_streamer.stream_success(
            run_id="test-run",
            message="Operation successful"
        )
        
        mock_redis.publish.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('app.services.vm_console_streamer.redis_client')
    async def test_stream_table(self, mock_redis):
        """Test table streaming."""
        mock_redis.publish = AsyncMock()
        
        await vm_console_streamer.stream_table(
            run_id="test-run",
            title="Test Table",
            headers=["Name", "Status"],
            rows=[["Item 1", "Active"], ["Item 2", "Inactive"]]
        )
        
        mock_redis.publish.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('app.services.vm_console_streamer.redis_client')
    async def test_request_approval(self, mock_redis):
        """Test approval request."""
        mock_redis.publish = AsyncMock()
        
        result = await vm_console_streamer.request_approval(
            run_id="test-run",
            message="Approve deployment?",
            command="deploy to production",
            timeout=1800
        )
        
        assert "approval_id" in result
        assert result["timeout"] == 1800
        mock_redis.publish.assert_called_once()


class TestWorkflowStateStore:
    """Test workflow state store."""
    
    @pytest.mark.asyncio
    async def test_create_workflow(self):
        """Test workflow creation."""
        workflow_id = await workflow_state_store.create_workflow(
            repo_name="test-repo",
            environment="dev",
            intent="deploy",
            metadata={"language": "Python"},
            created_by="test-user"
        )
        
        assert workflow_id is not None
        assert len(workflow_id) == 36  # UUID length
    
    @pytest.mark.asyncio
    async def test_load_workflow(self):
        """Test workflow loading."""
        # Create workflow first
        workflow_id = await workflow_state_store.create_workflow(
            repo_name="test-repo",
            environment="dev",
            intent="deploy",
            metadata={},
            created_by="test-user"
        )
        
        # Load it
        workflow = await workflow_state_store.load_workflow(workflow_id)
        
        assert workflow is not None
        assert workflow["id"] == workflow_id
        assert workflow["repo_name"] == "test-repo"
    
    @pytest.mark.asyncio
    async def test_find_workflows(self):
        """Test workflow search."""
        # Create test workflow
        await workflow_state_store.create_workflow(
            repo_name="search-test-repo",
            environment="dev",
            intent="deploy",
            metadata={},
            created_by="test-user",
            feature_branch="feature/test"
        )
        
        # Search for it
        workflows = await workflow_state_store.find_workflows(
            repo_name="search-test-repo",
            environment="dev",
            feature_branch="feature/test"
        )
        
        assert len(workflows) > 0
        assert workflows[0]["repo_name"] == "search-test-repo"


class TestDevOpsAgentV5Integration:
    """Test complete DevOps V5 workflow integration."""
    
    @pytest.mark.asyncio
    @patch('app.agents.devops_agent_v5.devops_service')
    @patch('app.agents.devops_agent_v5.local_file_manager')
    @patch('app.agents.devops_agent_v5.critic_agent')
    @patch('app.agents.devops_agent_v5.vm_console_streamer')
    async def test_complete_workflow(
        self,
        mock_streamer,
        mock_critic,
        mock_file_manager,
        mock_devops_service
    ):
        """Test complete DevOps workflow execution."""
        # Mock all dependencies
        mock_devops_service.ensure_repo_exists = AsyncMock(return_value={
            "repo_url": "https://github.com/test/test-repo",
            "source": "created"
        })
        
        mock_devops_service.detect_project_metadata = Mock(return_value=Mock(
            language=Mock(value="Python"),
            project_type="backend",
            package_manager="pip"
        ))
        
        mock_file_manager.clone_repository = AsyncMock(return_value={
            "local_path": "/tmp/test-repo",
            "source": "created"
        })
        
        mock_file_manager.create_branch = AsyncMock(return_value={
            "branch_name": "devops-dev",
            "source": "created"
        })
        
        mock_file_manager.write_files = AsyncMock(return_value={
            "files_written": 5,
            "total_files": 5
        })
        
        mock_file_manager.commit_and_push = AsyncMock(return_value={
            "commit_sha": "abc123",
            "changes_committed": True
        })
        
        mock_devops_service.get_file_generation_prompt = Mock(return_value="Generate files...")
        mock_devops_service.parse_generated_files = Mock(return_value=[
            Mock(path="app.py", content="# App code"),
            Mock(path="Dockerfile", content="FROM python:3.11")
        ])
        
        mock_critic.review_and_improve = AsyncMock(return_value=(
            {"app.py": "# Improved code"},
            [Mock(overall_score=8.5, approved=True)]
        ))
        
        mock_streamer.stream_message = AsyncMock()
        mock_streamer.stream_workflow_step = AsyncMock()
        mock_streamer.stream_box = AsyncMock()
        mock_streamer.request_approval = AsyncMock(return_value={"approval_id": "test-approval"})
        
        # Execute workflow
        result = await devops_agent_v5.execute_workflow(
            run_id="test-run",
            user_prompt="create a python flask app",
            repo_name="test-repo",
            target_environment="dev",
            enable_critic=True,
            auto_approve=True
        )
        
        # Verify result
        assert result is not None
        assert result.get("status") in ["RUNNING", "COMPLETED", "PAUSED"]
        assert "repo_url" in result or "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
