"""Master test file for DevOps agent integration.

Tests GitHub operations, file generation, and workflow execution.
Per HLD: DevOps Agent – Interacts with Github for push, pull, merge, PR, reviews, github actions and gitops
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Import schemas
from app.schemas.devops_schemas import (
    WorkflowStep, WorkflowStatus, ProjectMetadata, ProjectLanguage,
    TargetEnvironment, DevOpsWorkflowResult, GeneratedFile,
    PRInfo, PRMergeResult, RepoInfo
)


# ===================================
# Fixtures
# ===================================

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    if asyncio.sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_github_client():
    """Mock GitHub client."""
    with patch("app.clients.github_client.GitHubClient") as mock:
        client = mock.return_value
        client.is_configured = True
        client.token = "test_token"
        client.username = "test_user"
        
        # Mock methods
        client.get_repo = AsyncMock(return_value={
            "name": "test-repo",
            "full_name": "test_user/test-repo",
            "html_url": "https://github.com/test_user/test-repo",
            "clone_url": "https://github.com/test_user/test-repo.git",
            "default_branch": "main",
            "private": False
        })
        
        client.create_repo = AsyncMock(return_value={
            "name": "test-repo",
            "html_url": "https://github.com/test_user/test-repo",
            "clone_url": "https://github.com/test_user/test-repo.git"
        })
        
        client.repo_exists = AsyncMock(return_value=True)
        
        client.create_pull_request = AsyncMock(return_value={
            "number": 1,
            "title": "Test PR",
            "html_url": "https://github.com/test_user/test-repo/pull/1",
            "state": "open",
            "head_branch": "feature",
            "base_branch": "main"
        })
        
        client.merge_pull_request = AsyncMock(return_value={
            "merged": True,
            "sha": "abc123",
            "message": "PR merged"
        })
        
        client.list_pull_requests = AsyncMock(return_value=[])
        client.find_pr_by_branch = AsyncMock(return_value=None)
        
        client.trigger_workflow = AsyncMock(return_value={
            "status": "triggered",
            "workflow_id": "ci.yml"
        })
        
        client.list_workflow_runs = AsyncMock(return_value=[])
        
        client.create_or_update_secret = AsyncMock(return_value={
            "name": "TEST_SECRET",
            "status": "created"
        })
        
        client.create_or_update_file = AsyncMock(return_value={
            "content": {"sha": "abc123"},
            "commit": {"sha": "def456"}
        })
        
        yield client


@pytest.fixture
def mock_llm_client():
    """Mock LLM client."""
    with patch("app.services.llm_client.llm_client") as mock:
        mock.generate = AsyncMock(return_value='''{
            "files": [
                {"path": "app.py", "content": "from flask import Flask\\napp = Flask(__name__)"},
                {"path": "requirements.txt", "content": "flask==3.0.0"},
                {"path": "Dockerfile", "content": "FROM python:3.11-slim"}
            ]
        }''')
        yield mock


@pytest.fixture
def sample_workflow_request():
    """Sample workflow request."""
    return {
        "user_prompt": "Create a Python Flask API with health endpoint",
        "repo_name": "test-flask-api",
        "target_environment": "dev",
        "feature_branch": None,
        "approval_required": False,
        "auto_approve": True
    }


# ===================================
# Schema Tests
# ===================================

class TestDevOpsSchemas:
    """Test DevOps Pydantic schemas."""
    
    def test_workflow_step_enum(self):
        """Test WorkflowStep enum values."""
        print("\n  === Testing WorkflowStep Enum ===")
        print(f"  WorkflowStep.INIT.value = '{WorkflowStep.INIT.value}' (expected: 'INIT')")
        assert WorkflowStep.INIT.value == "INIT"
        print(f"  WorkflowStep.REPO_READY.value = '{WorkflowStep.REPO_READY.value}' (expected: 'REPO_READY')")
        assert WorkflowStep.REPO_READY.value == "REPO_READY"
        print(f"  WorkflowStep.FILES_READY.value = '{WorkflowStep.FILES_READY.value}' (expected: 'FILES_READY')")
        assert WorkflowStep.FILES_READY.value == "FILES_READY"
        print(f"  WorkflowStep.CHANGES_PUSHED.value = '{WorkflowStep.CHANGES_PUSHED.value}' (expected: 'CHANGES_PUSHED')")
        assert WorkflowStep.CHANGES_PUSHED.value == "CHANGES_PUSHED"
        print(f"  WorkflowStep.SECRETS_READY.value = '{WorkflowStep.SECRETS_READY.value}' (expected: 'SECRETS_READY')")
        assert WorkflowStep.SECRETS_READY.value == "SECRETS_READY"
        print(f"  WorkflowStep.PR_READY.value = '{WorkflowStep.PR_READY.value}' (expected: 'PR_READY')")
        assert WorkflowStep.PR_READY.value == "PR_READY"
        print(f"  WorkflowStep.DEPLOYED.value = '{WorkflowStep.DEPLOYED.value}' (expected: 'DEPLOYED')")
        assert WorkflowStep.DEPLOYED.value == "DEPLOYED"
        print("  ✓ All WorkflowStep enum values verified")
    
    def test_workflow_status_enum(self):
        """Test WorkflowStatus enum values."""
        print("\n  === Testing WorkflowStatus Enum ===")
        print(f"  WorkflowStatus.PENDING.value = '{WorkflowStatus.PENDING.value}' (expected: 'PENDING')")
        assert WorkflowStatus.PENDING.value == "PENDING"
        print(f"  WorkflowStatus.RUNNING.value = '{WorkflowStatus.RUNNING.value}' (expected: 'RUNNING')")
        assert WorkflowStatus.RUNNING.value == "RUNNING"
        print(f"  WorkflowStatus.PAUSED.value = '{WorkflowStatus.PAUSED.value}' (expected: 'PAUSED')")
        assert WorkflowStatus.PAUSED.value == "PAUSED"
        print(f"  WorkflowStatus.COMPLETED.value = '{WorkflowStatus.COMPLETED.value}' (expected: 'COMPLETED')")
        assert WorkflowStatus.COMPLETED.value == "COMPLETED"
        print(f"  WorkflowStatus.FAILED.value = '{WorkflowStatus.FAILED.value}' (expected: 'FAILED')")
        assert WorkflowStatus.FAILED.value == "FAILED"
        print("  ✓ All WorkflowStatus enum values verified")
    
    def test_project_language_enum(self):
        """Test ProjectLanguage enum values."""
        print("\n  === Testing ProjectLanguage Enum ===")
        print(f"  ProjectLanguage.PYTHON.value = '{ProjectLanguage.PYTHON.value}' (expected: 'Python')")
        assert ProjectLanguage.PYTHON.value == "Python"
        print(f"  ProjectLanguage.JAVASCRIPT.value = '{ProjectLanguage.JAVASCRIPT.value}' (expected: 'JavaScript')")
        assert ProjectLanguage.JAVASCRIPT.value == "JavaScript"
        print(f"  ProjectLanguage.TYPESCRIPT.value = '{ProjectLanguage.TYPESCRIPT.value}' (expected: 'TypeScript')")
        assert ProjectLanguage.TYPESCRIPT.value == "TypeScript"
        print(f"  ProjectLanguage.JAVA.value = '{ProjectLanguage.JAVA.value}' (expected: 'Java')")
        assert ProjectLanguage.JAVA.value == "Java"
        print(f"  ProjectLanguage.GO.value = '{ProjectLanguage.GO.value}' (expected: 'Go')")
        assert ProjectLanguage.GO.value == "Go"
        print("  ✓ All ProjectLanguage enum values verified")
    
    def test_target_environment_enum(self):
        """Test TargetEnvironment enum values."""
        print("\n  === Testing TargetEnvironment Enum ===")
        print(f"  TargetEnvironment.DEV.value = '{TargetEnvironment.DEV.value}' (expected: 'dev')")
        assert TargetEnvironment.DEV.value == "dev"
        print(f"  TargetEnvironment.STAGING.value = '{TargetEnvironment.STAGING.value}' (expected: 'staging')")
        assert TargetEnvironment.STAGING.value == "staging"
        print(f"  TargetEnvironment.PROD.value = '{TargetEnvironment.PROD.value}' (expected: 'prod')")
        assert TargetEnvironment.PROD.value == "prod"
        print("  ✓ All TargetEnvironment enum values verified")
    
    def test_project_metadata_schema(self):
        """Test ProjectMetadata schema."""
        print("\n  === Testing ProjectMetadata Schema ===")
        metadata = ProjectMetadata(
            language=ProjectLanguage.PYTHON,
            project_type="backend",
            package_manager="pip"
        )
        print(f"  Created ProjectMetadata: language={metadata.language}, project_type='{metadata.project_type}', package_manager='{metadata.package_manager}'")
        
        print(f"  metadata.language = {metadata.language} (expected: ProjectLanguage.PYTHON)")
        assert metadata.language == ProjectLanguage.PYTHON
        print(f"  metadata.project_type = '{metadata.project_type}' (expected: 'backend')")
        assert metadata.project_type == "backend"
        print(f"  metadata.package_manager = '{metadata.package_manager}' (expected: 'pip')")
        assert metadata.package_manager == "pip"
        print("  ✓ ProjectMetadata schema validated")
    
    def test_pr_info_schema(self):
        """Test PRInfo schema."""
        print("\n  === Testing PRInfo Schema ===")
        pr = PRInfo(
            number=1,
            title="Test PR",
            state="open",
            html_url="https://github.com/test/repo/pull/1",
            head_branch="feature",
            base_branch="main"
        )
        print(f"  Created PRInfo: number={pr.number}, title='{pr.title}', state='{pr.state}'")
        print(f"  html_url='{pr.html_url}', head_branch='{pr.head_branch}', base_branch='{pr.base_branch}'")
        
        print(f"  pr.number = {pr.number} (expected: 1)")
        assert pr.number == 1
        print(f"  pr.title = '{pr.title}' (expected: 'Test PR')")
        assert pr.title == "Test PR"
        print(f"  pr.state = '{pr.state}' (expected: 'open')")
        assert pr.state == "open"
        print("  ✓ PRInfo schema validated")
    
    def test_pr_merge_result_schema(self):
        """Test PRMergeResult schema."""
        print("\n  === Testing PRMergeResult Schema ===")
        result = PRMergeResult(
            merged=True,
            sha="abc123",
            message="PR merged successfully"
        )
        print(f"  Created PRMergeResult: merged={result.merged}, sha='{result.sha}', message='{result.message}'")
        
        print(f"  result.merged = {result.merged} (expected: True)")
        assert result.merged is True
        print(f"  result.sha = '{result.sha}' (expected: 'abc123')")
        assert result.sha == "abc123"
        print("  ✓ PRMergeResult schema validated")
    
    def test_generated_file_schema(self):
        """Test GeneratedFile schema."""
        print("\n  === Testing GeneratedFile Schema ===")
        file = GeneratedFile(
            path="app.py",
            content="print('hello')",
            file_type="app"
        )
        print(f"  Created GeneratedFile: path='{file.path}', file_type='{file.file_type}'")
        print(f"  content='{file.content}'")
        
        print(f"  file.path = '{file.path}' (expected: 'app.py')")
        assert file.path == "app.py"
        print(f"  file.file_type = '{file.file_type}' (expected: 'app')")
        assert file.file_type == "app"
        print("  ✓ GeneratedFile schema validated")
    
    def test_devops_workflow_result_schema(self):
        """Test DevOpsWorkflowResult schema."""
        print("\n  === Testing DevOpsWorkflowResult Schema ===")
        result = DevOpsWorkflowResult(
            workflow_id="test-123",
            status=WorkflowStatus.COMPLETED,
            current_state=WorkflowStep.DEPLOYED,
            repo_url="https://github.com/test/repo",
            pr_url="https://github.com/test/repo/pull/1",
            deployment_triggered=True
        )
        print(f"  Created DevOpsWorkflowResult:")
        print(f"    workflow_id='{result.workflow_id}'")
        print(f"    status={result.status}")
        print(f"    current_state={result.current_state}")
        print(f"    repo_url='{result.repo_url}'")
        print(f"    pr_url='{result.pr_url}'")
        print(f"    deployment_triggered={result.deployment_triggered}")
        
        print(f"  result.workflow_id = '{result.workflow_id}' (expected: 'test-123')")
        assert result.workflow_id == "test-123"
        print(f"  result.status = {result.status} (expected: WorkflowStatus.COMPLETED)")
        assert result.status == WorkflowStatus.COMPLETED
        print(f"  result.deployment_triggered = {result.deployment_triggered} (expected: True)")
        assert result.deployment_triggered is True
        print("  ✓ DevOpsWorkflowResult schema validated")


# ===================================
# Service Tests
# ===================================

class TestDevOpsService:
    """Test DevOps service layer."""
    
    def test_service_initialization(self):
        """Test service initialization."""
        print("\n  === Testing DevOpsService Initialization ===")
        from app.services.devops_service import DevOpsService
        
        service = DevOpsService()
        print(f"  service = DevOpsService()")
        print(f"  service is not None: {service is not None}")
        assert service is not None
        print(f"  service.port_map = {service.port_map}")
        assert service.port_map is not None
        print(f"  service.package_manager_map = {service.package_manager_map}")
        assert service.package_manager_map is not None
        print("  ✓ DevOpsService initialized successfully")
    
    def test_detect_python_project(self):
        """Test Python project detection."""
        print("\n  === Testing Python Project Detection ===")
        from app.services.devops_service import devops_service
        
        prompt = "Create a python flask api with REST endpoints"
        print(f"  Input prompt: '{prompt}'")
        
        metadata = devops_service.detect_project_metadata(prompt)
        print(f"  Detected language: {metadata.language} (expected: ProjectLanguage.PYTHON)")
        assert metadata.language == ProjectLanguage.PYTHON
        print(f"  Detected package_manager: '{metadata.package_manager}' (expected: 'pip')")
        assert metadata.package_manager == "pip"
        print("  ✓ Python project detected correctly")
    
    def test_detect_javascript_project(self):
        """Test JavaScript project detection."""
        print("\n  === Testing JavaScript Project Detection ===")
        from app.services.devops_service import devops_service
        
        prompt = "Create a Node.js Express server"
        print(f"  Input prompt: '{prompt}'")
        
        metadata = devops_service.detect_project_metadata(prompt)
        print(f"  Detected language: {metadata.language} (expected: ProjectLanguage.JAVASCRIPT)")
        assert metadata.language == ProjectLanguage.JAVASCRIPT
        print(f"  Detected package_manager: '{metadata.package_manager}' (expected: 'npm')")
        assert metadata.package_manager == "npm"
        print("  ✓ JavaScript project detected correctly")
    
    def test_detect_typescript_project(self):
        """Test TypeScript project detection."""
        print("\n  === Testing TypeScript Project Detection ===")
        from app.services.devops_service import devops_service
        
        prompt = "Create a typescript nestjs application"
        print(f"  Input prompt: '{prompt}'")
        
        metadata = devops_service.detect_project_metadata(prompt)
        print(f"  Detected language: {metadata.language} (expected: ProjectLanguage.TYPESCRIPT)")
        assert metadata.language == ProjectLanguage.TYPESCRIPT
        print(f"  Detected package_manager: '{metadata.package_manager}' (expected: 'npm')")
        assert metadata.package_manager == "npm"
        print("  ✓ TypeScript project detected correctly")
    
    def test_detect_java_project(self):
        """Test Java project detection."""
        print("\n  === Testing Java Project Detection ===")
        from app.services.devops_service import devops_service
        
        prompt = "Create a Java Spring Boot microservice"
        print(f"  Input prompt: '{prompt}'")
        
        metadata = devops_service.detect_project_metadata(prompt)
        print(f"  Detected language: {metadata.language} (expected: ProjectLanguage.JAVA)")
        assert metadata.language == ProjectLanguage.JAVA
        print(f"  Detected package_manager: '{metadata.package_manager}' (expected: 'maven')")
        assert metadata.package_manager == "maven"
        print("  ✓ Java project detected correctly")
    
    def test_detect_go_project(self):
        """Test Go project detection."""
        print("\n  === Testing Go Project Detection ===")
        from app.services.devops_service import devops_service
        
        prompt = "Create a Go Gin REST API"
        print(f"  Input prompt: '{prompt}'")
        
        metadata = devops_service.detect_project_metadata(prompt)
        print(f"  Detected language: {metadata.language} (expected: ProjectLanguage.GO)")
        assert metadata.language == ProjectLanguage.GO
        print(f"  Detected package_manager: '{metadata.package_manager}' (expected: 'go')")
        assert metadata.package_manager == "go"
        print("  ✓ Go project detected correctly")
    
    def test_get_app_port_python(self):
        """Test Python app port."""
        print("\n  === Testing Python App Port ===")
        from app.services.devops_service import devops_service
        
        port = devops_service.get_app_port(ProjectLanguage.PYTHON)
        print(f"  devops_service.get_app_port(ProjectLanguage.PYTHON) = {port} (expected: 5000)")
        assert port == 5000
        print("  ✓ Python port is correct")
    
    def test_get_app_port_javascript(self):
        """Test JavaScript app port."""
        print("\n  === Testing JavaScript App Port ===")
        from app.services.devops_service import devops_service
        
        port = devops_service.get_app_port(ProjectLanguage.JAVASCRIPT)
        print(f"  devops_service.get_app_port(ProjectLanguage.JAVASCRIPT) = {port} (expected: 3000)")
        assert port == 3000
        print("  ✓ JavaScript port is correct")
    
    def test_get_app_port_java(self):
        """Test Java app port."""
        print("\n  === Testing Java App Port ===")
        from app.services.devops_service import devops_service
        
        port = devops_service.get_app_port(ProjectLanguage.JAVA)
        print(f"  devops_service.get_app_port(ProjectLanguage.JAVA) = {port} (expected: 8080)")
        assert port == 8080
        print("  ✓ Java port is correct")
    
    def test_file_generation_prompt(self):
        """Test file generation prompt creation."""
        print("\n  === Testing File Generation Prompt ===")
        from app.services.devops_service import devops_service
        
        metadata = ProjectMetadata(
            language=ProjectLanguage.PYTHON,
            project_type="backend",
            package_manager="pip"
        )
        print(f"  metadata: language={metadata.language}, project_type='{metadata.project_type}', package_manager='{metadata.package_manager}'")
        
        prompt = devops_service.get_file_generation_prompt(
            user_prompt="Create a Flask API",
            metadata=metadata,
            project_name="test-api",
            environment="dev"
        )
        print(f"  Generated prompt length: {len(prompt)} characters")
        print(f"  Prompt preview: {prompt[:200]}...")
        
        has_flask = "Flask" in prompt or "PYTHON" in prompt
        print(f"  Contains 'Flask' or 'PYTHON': {has_flask}")
        assert has_flask
        print(f"  Contains 'test-api': {'test-api' in prompt}")
        assert "test-api" in prompt
        print(f"  Contains 'dev': {'dev' in prompt}")
        assert "dev" in prompt
        print("  ✓ File generation prompt created correctly")
    
    def test_parse_generated_files(self):
        """Test parsing LLM response."""
        print("\n  === Testing Parse Generated Files (JSON) ===")
        from app.services.devops_service import devops_service
        
        response = '''{
            "files": [
                {"path": "app.py", "content": "from flask import Flask"},
                {"path": "requirements.txt", "content": "flask==3.0.0"}
            ]
        }'''
        print(f"  Input JSON response: {response[:100]}...")
        
        files = devops_service.parse_generated_files(response)
        print(f"  Parsed {len(files)} files (expected: 2)")
        assert len(files) == 2
        print(f"  files[0].path = '{files[0].path}' (expected: 'app.py')")
        assert files[0].path == "app.py"
        print(f"  files[1].path = '{files[1].path}' (expected: 'requirements.txt')")
        assert files[1].path == "requirements.txt"
        print("  ✓ JSON response parsed correctly")
    
    def test_parse_generated_files_with_markdown(self):
        """Test parsing LLM response with markdown code blocks."""
        print("\n  === Testing Parse Generated Files (Markdown) ===")
        from app.services.devops_service import devops_service
        
        response = '''```json
{
    "files": [
        {"path": "app.py", "content": "print('hello')"}
    ]
}
```'''
        print(f"  Input markdown response with code block")
        
        files = devops_service.parse_generated_files(response)
        print(f"  Parsed {len(files)} files (expected: 1)")
        assert len(files) == 1
        print(f"  files[0].path = '{files[0].path}' (expected: 'app.py')")
        assert files[0].path == "app.py"
        print("  ✓ Markdown code block parsed correctly")


# ===================================
# Agent Tests
# ===================================

class TestDevOpsAgent:
    """Test DevOps agent."""
    
    def test_agent_initialization(self):
        """Test agent initialization."""
        print("\n  === Testing DevOpsAgent Initialization ===")
        from app.agents.devops_agent import DevOpsAgent
        
        agent = DevOpsAgent()
        print(f"  agent = DevOpsAgent()")
        print(f"  agent is not None: {agent is not None}")
        assert agent is not None
        print(f"  agent.service is not None: {agent.service is not None}")
        assert agent.service is not None
        print(f"  agent.github is not None: {agent.github is not None}")
        assert agent.github is not None
        print("  ✓ DevOpsAgent initialized successfully")
    
    def test_create_initial_state(self):
        """Test initial state creation."""
        print("\n  === Testing Create Initial State ===")
        from app.agents.devops_agent import DevOpsAgent
        
        agent = DevOpsAgent()
        state = agent._create_initial_state(
            user_prompt="Create a Flask API",
            repo_name="test-api",
            target_environment="dev",
            feature_branch=None,
            approval_required=True,
            workflow_id="test-123"
        )
        print(f"  Created initial state with:")
        print(f"    user_prompt: '{state['user_prompt']}'")
        print(f"    repo_name: '{state['repo_name']}'")
        print(f"    target_environment: '{state['target_environment']}'")
        print(f"    workflow_id: '{state['workflow_id']}'")
        print(f"    current_state: '{state['current_state']}'")
        print(f"    status: '{state['status']}'")
        
        print(f"  state['user_prompt'] = '{state['user_prompt']}' (expected: 'Create a Flask API')")
        assert state["user_prompt"] == "Create a Flask API"
        print(f"  state['repo_name'] = '{state['repo_name']}' (expected: 'test-api')")
        assert state["repo_name"] == "test-api"
        print(f"  state['target_environment'] = '{state['target_environment']}' (expected: 'dev')")
        assert state["target_environment"] == "dev"
        print(f"  state['workflow_id'] = '{state['workflow_id']}' (expected: 'test-123')")
        assert state["workflow_id"] == "test-123"
        print(f"  state['current_state'] = '{state['current_state']}' (expected: '{WorkflowStep.INIT.value}')")
        assert state["current_state"] == WorkflowStep.INIT.value
        print(f"  state['status'] = '{state['status']}' (expected: '{WorkflowStatus.RUNNING.value}')")
        assert state["status"] == WorkflowStatus.RUNNING.value
        print("  ✓ Initial state created correctly")
    
    def test_create_result(self):
        """Test result creation from state."""
        print("\n  === Testing Create Result from State ===")
        from app.agents.devops_agent import DevOpsAgent
        
        agent = DevOpsAgent()
        state = {
            "workflow_id": "test-123",
            "status": WorkflowStatus.COMPLETED.value,
            "current_state": WorkflowStep.DEPLOYED.value,
            "repo_url": "https://github.com/test/repo",
            "pr_url": "https://github.com/test/repo/pull/1",
            "deployment_triggered": True,
            "error": None,
            "artifacts": {"files_count": 5}
        }
        print(f"  Input state: {state}")
        
        result = agent._create_result(state)
        print(f"  Created result:")
        print(f"    workflow_id: '{result.workflow_id}'")
        print(f"    status: {result.status}")
        print(f"    current_state: {result.current_state}")
        print(f"    deployment_triggered: {result.deployment_triggered}")
        
        print(f"  result.workflow_id = '{result.workflow_id}' (expected: 'test-123')")
        assert result.workflow_id == "test-123"
        print(f"  result.status = {result.status} (expected: WorkflowStatus.COMPLETED)")
        assert result.status == WorkflowStatus.COMPLETED
        print(f"  result.current_state = {result.current_state} (expected: WorkflowStep.DEPLOYED)")
        assert result.current_state == WorkflowStep.DEPLOYED
        print(f"  result.deployment_triggered = {result.deployment_triggered} (expected: True)")
        assert result.deployment_triggered is True
        print("  ✓ Result created correctly from state")
    
    def test_generate_workflow_id(self):
        """Test workflow ID generation."""
        print("\n  === Testing Workflow ID Generation ===")
        from app.agents.devops_agent import DevOpsAgent
        
        agent = DevOpsAgent()
        id1 = agent._generate_workflow_id()
        id2 = agent._generate_workflow_id()
        
        print(f"  Generated ID 1: '{id1}'")
        print(f"  Generated ID 2: '{id2}'")
        print(f"  IDs are unique: {id1 != id2}")
        assert id1 != id2
        print(f"  ID 1 length: {len(id1)} (expected: 36 for UUID)")
        assert len(id1) == 36  # UUID format
        print(f"  ID 2 length: {len(id2)} (expected: 36 for UUID)")
        assert len(id2) == 36
        print("  ✓ Workflow IDs generated correctly")


# ===================================
# GitHub Client Tests
# ===================================

class TestGitHubClient:
    """Test GitHub client."""
    
    def test_client_initialization(self):
        """Test client initialization."""
        print("\n  === Testing GitHubClient Initialization ===")
        from app.clients.github_client import GitHubClient
        
        client = GitHubClient(
            token="test_token",
            username="test_user"
        )
        print(f"  client = GitHubClient(token='test_token', username='test_user')")
        
        print(f"  client.token = '{client.token}' (expected: 'test_token')")
        assert client.token == "test_token"
        print(f"  client.username = '{client.username}' (expected: 'test_user')")
        assert client.username == "test_user"
        print(f"  client.is_configured = {client.is_configured} (expected: True)")
        assert client.is_configured is True
        print("  ✓ GitHubClient initialized correctly")
    
    def test_client_not_configured(self):
        """Test client not configured."""
        print("\n  === Testing GitHubClient Not Configured ===")
        from app.clients.github_client import GitHubClient
        
        client = GitHubClient(token=None, username=None)
        print(f"  client = GitHubClient(token=None, username=None)")
        print(f"  client.is_configured = {client.is_configured} (expected: False)")
        assert client.is_configured is False
        print("  ✓ Unconfigured client detected correctly")
    
    def test_extract_repo_name(self):
        """Test repo name extraction from URL."""
        print("\n  === Testing Repo Name Extraction ===")
        from app.clients.github_client import GitHubClient
        
        # HTTPS URL
        url1 = "https://github.com/owner/repo"
        name1 = GitHubClient.extract_repo_name(url1)
        print(f"  Input URL: '{url1}'")
        print(f"  Extracted name: '{name1}' (expected: 'owner/repo')")
        assert name1 == "owner/repo"
        
        # HTTPS URL with .git
        url2 = "https://github.com/owner/repo.git"
        name2 = GitHubClient.extract_repo_name(url2)
        print(f"  Input URL: '{url2}'")
        print(f"  Extracted name: '{name2}' (expected: 'owner/repo')")
        assert name2 == "owner/repo"
        print("  ✓ Repo names extracted correctly")
    
    def test_get_auth_url(self):
        """Test authenticated URL generation."""
        print("\n  === Testing Authenticated URL Generation ===")
        from app.clients.github_client import GitHubClient
        
        client = GitHubClient(
            token="test_token",
            username="test_user"
        )
        
        url = "https://github.com/owner/repo"
        auth_url = client.get_auth_url(url)
        print(f"  Input URL: '{url}'")
        print(f"  Auth URL: '{auth_url}'")
        print(f"  Contains 'test_user:test_token@': {'test_user:test_token@' in auth_url}")
        assert "test_user:test_token@" in auth_url
        print("  ✓ Authenticated URL generated correctly")


# ===================================
# API Tests (Mocked)
# ===================================

class TestDevOpsAPI:
    """Test DevOps API endpoints."""
    
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        """Test health endpoint."""
        print("\n  === Testing DevOps Health Endpoint ===")
        from app.api.devops import devops_health
        
        result = await devops_health()
        print(f"  Response: {result}")
        
        print(f"  result['status'] = '{result['status']}' (expected: 'healthy')")
        assert result["status"] == "healthy"
        print(f"  'configured' in result: {'configured' in result}")
        assert "configured" in result
        print("  ✓ Health endpoint working correctly")
    
    @pytest.mark.asyncio
    async def test_status_endpoint(self):
        """Test status endpoint."""
        print("\n  === Testing DevOps Status Endpoint ===")
        from app.api.devops import devops_status
        
        result = await devops_status()
        print(f"  Response: {result}")
        
        print(f"  result['service'] = '{result['service']}' (expected: 'devops')")
        assert result["service"] == "devops"
        print(f"  'features' in result: {'features' in result}")
        assert "features" in result
        print(f"  result['features']['repo_management'] = {result['features']['repo_management']} (expected: True)")
        assert result["features"]["repo_management"] is True
        print("  ✓ Status endpoint working correctly")


# ===================================
# Integration Tests (Skipped without credentials)
# ===================================

class TestDevOpsIntegration:
    """Integration tests requiring GitHub credentials."""
    
    @pytest.fixture
    def skip_without_credentials(self):
        """Skip test if credentials not configured."""
        from app.services.devops_service import devops_service
        
        if not devops_service.is_configured:
            pytest.skip("GitHub credentials not configured")
    
    @pytest.mark.asyncio
    async def test_live_repo_operations(self):
        """Test LIVE repository operations - creates actual repo on GitHub."""
        print("\n  === LIVE TEST: GitHub Repository Operations ===")
        from app.clients.github_client import github_client
        from app.services.devops_service import devops_service
        import time
        
        if not github_client.is_configured:
            pytest.skip("GitHub credentials not configured")
        
        # Generate unique test repo name
        test_repo_name = f"test-devops-agent-{int(time.time())}"
        print(f"  Creating test repository: {test_repo_name}")
        print(f"  GitHub Username: {github_client.username}")
        
        try:
            # Step 1: Create repository
            print("\n  [Step 1] Creating repository...")
            repo = await github_client.create_repo(
                name=test_repo_name,
                description="Test repo created by DevOps Agent integration test",
                private=True,
                auto_init=True
            )
            print(f"    ✓ Repository created: {repo.get('html_url', 'N/A')}")
            print(f"    Name: {repo.get('name')}")
            print(f"    Full name: {repo.get('full_name')}")
            print(f"    Clone URL: {repo.get('clone_url')}")
            print(f"    Default branch: {repo.get('default_branch', 'main')}")
            
            # Small delay to allow GitHub to propagate
            import asyncio
            await asyncio.sleep(2)
            
            # Step 2: Check if repo exists (pass owner and repo separately)
            print("\n  [Step 2] Verifying repository exists...")
            exists = await github_client.repo_exists(owner=github_client.username, repo=test_repo_name)
            print(f"    ✓ Repository exists: {exists}")
            assert exists is True
            
            # Step 3: Create a file
            print("\n  [Step 3] Creating README.md file...")
            readme_content = f"""# {test_repo_name}

This is a test repository created by the DevOps Agent integration test.

## Created
- Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}
- Test: test_live_repo_operations

## Purpose
Validates that the DevOps agent can:
- Create repositories
- Push files
- Create branches
- Create pull requests
"""
            file_result = await github_client.create_or_update_file(
                repo=test_repo_name,
                path="README.md",
                content=readme_content,
                message="Initial commit - README.md",
                branch="main"
            )
            print(f"    ✓ File created/updated")
            print(f"    Commit SHA: {file_result.get('commit', {}).get('sha', 'N/A')[:8]}...")
            
            # Step 4: Create app.py file
            print("\n  [Step 4] Creating app.py file...")
            app_content = '''"""Simple Flask application created by DevOps Agent."""
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "service": "test-app"})

@app.route("/")
def index():
    return jsonify({"message": "Hello from DevOps Agent!"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
'''
            await github_client.create_or_update_file(
                repo=test_repo_name,
                path="app.py",
                content=app_content,
                message="Add Flask application",
                branch="main"
            )
            print(f"    ✓ app.py created")
            
            # Step 5: Create requirements.txt
            print("\n  [Step 5] Creating requirements.txt...")
            requirements_content = """flask==3.0.0
gunicorn==21.2.0
"""
            await github_client.create_or_update_file(
                repo=test_repo_name,
                path="requirements.txt",
                content=requirements_content,
                message="Add requirements.txt",
                branch="main"
            )
            print(f"    ✓ requirements.txt created")
            
            # Step 6: Create a feature branch by getting main ref and creating new ref
            print("\n  [Step 6] Creating feature branch...")
            branch_name = "feature/add-dockerfile"
            try:
                # Get the SHA of main branch
                main_branch = await github_client.get_branch(
                    branch="main",
                    owner=github_client.username,
                    repo=test_repo_name
                )
                main_sha = main_branch["commit"]["sha"]
                print(f"    Main branch SHA: {main_sha[:8]}...")
                
                # Create new branch ref
                client = await github_client._get_client()
                response = await client.post(
                    f"/repos/{github_client.username}/{test_repo_name}/git/refs",
                    json={
                        "ref": f"refs/heads/{branch_name}",
                        "sha": main_sha
                    }
                )
                if response.status_code < 300:
                    print(f"    ✓ Branch created: {branch_name}")
                else:
                    print(f"    ⚠ Branch creation response: {response.status_code}")
            except Exception as e:
                print(f"    ⚠ Branch creation: {e}")
            
            # Step 7: Add Dockerfile to feature branch
            print("\n  [Step 7] Adding Dockerfile to feature branch...")
            dockerfile_content = """FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
"""
            await github_client.create_or_update_file(
                repo=test_repo_name,
                path="Dockerfile",
                content=dockerfile_content,
                message="Add Dockerfile for containerization",
                branch=branch_name
            )
            print(f"    ✓ Dockerfile added to {branch_name}")
            
            # Step 8: Create Pull Request
            print("\n  [Step 8] Creating Pull Request...")
            pr = await github_client.create_pull_request(
                repo=test_repo_name,
                title="Add Dockerfile for containerization",
                body="""## Changes
- Added Dockerfile for containerization
- Uses Python 3.11-slim base image
- Configured gunicorn for production

## Testing
- Build: `docker build -t test-app .`
- Run: `docker run -p 5000:5000 test-app`

Created by DevOps Agent integration test.
""",
                head=branch_name,
                base="main"
            )
            print(f"    ✓ Pull Request created!")
            print(f"    PR Number: #{pr.get('number')}")
            print(f"    PR Title: {pr.get('title')}")
            print(f"    PR URL: {pr.get('html_url')}")
            print(f"    State: {pr.get('state')}")
            
            # Step 9: List PRs
            print("\n  [Step 9] Listing open Pull Requests...")
            prs = await github_client.list_pull_requests(
                repo=test_repo_name,
                owner=github_client.username,
                state="open"
            )
            print(f"    ✓ Found {len(prs)} open PR(s)")
            for p in prs:
                print(f"      - #{p.get('number')}: {p.get('title')}")
            
            # Step 10: Get repo info
            print("\n  [Step 10] Getting repository info...")
            repo_info = await github_client.get_repo(owner=github_client.username, repo=test_repo_name)
            print(f"    ✓ Repository info retrieved")
            print(f"    Stars: {repo_info.get('stargazers_count', 0)}")
            print(f"    Forks: {repo_info.get('forks_count', 0)}")
            print(f"    Open Issues: {repo_info.get('open_issues_count', 0)}")
            print(f"    Size: {repo_info.get('size', 0)} KB")
            
            print("\n  ========================================")
            print(f"  ✓ ALL LIVE TESTS PASSED!")
            print(f"  Repository URL: https://github.com/{github_client.username}/{test_repo_name}")
            print(f"  PR URL: {pr.get('html_url')}")
            print("  ========================================")
            
            # Note: Not deleting the repo so you can inspect it
            print(f"\n  ℹ Repository NOT deleted - you can inspect it at:")
            print(f"    https://github.com/{github_client.username}/{test_repo_name}")
            
        except Exception as e:
            print(f"\n  ✗ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires GitHub credentials")
    async def test_repo_operations(self, skip_without_credentials):
        """Test repository operations."""
        from app.services.devops_service import devops_service
        
        # This would test actual GitHub operations
        pass
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires GitHub credentials")
    async def test_pr_operations(self, skip_without_credentials):
        """Test PR operations."""
        from app.agents.devops_agent import devops_agent
        
        # This would test actual PR operations
        pass
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires GitHub credentials")
    async def test_workflow_execution(self, skip_without_credentials):
        """Test full workflow execution."""
        from app.agents.devops_agent import devops_agent
        
        # This would test actual workflow execution
        pass


# ===================================
# Run Tests
# ===================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
