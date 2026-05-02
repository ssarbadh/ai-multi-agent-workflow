"""DevOps schemas for GitHub and GitOps operations.

Per HLD: DevOps Agent – Interacts with Github for push, pull, merge, PR, reviews, github actions and gitops
"""

from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class WorkflowStep(str, Enum):
    """Workflow state transitions for declarative execution."""
    INIT = "INIT"
    REPO_READY = "REPO_READY"
    WORKING_COPY_READY = "WORKING_COPY_READY"
    FILES_READY = "FILES_READY"
    CHANGES_PUSHED = "CHANGES_PUSHED"
    SECRETS_READY = "SECRETS_READY"
    PR_READY = "PR_READY"
    DEPLOYED = "DEPLOYED"


class WorkflowStatus(str, Enum):
    """Workflow execution status."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MergeMethod(str, Enum):
    """PR merge methods."""
    MERGE = "merge"
    SQUASH = "squash"
    REBASE = "rebase"


class ProjectLanguage(str, Enum):
    """Supported programming languages."""
    PYTHON = "Python"
    JAVASCRIPT = "JavaScript"
    TYPESCRIPT = "TypeScript"
    JAVA = "Java"
    GO = "Go"
    RUBY = "Ruby"
    PHP = "PHP"
    RUST = "Rust"
    CSHARP = "C#"
    CPP = "C++"
    C = "C"


class TargetEnvironment(str, Enum):
    """Deployment target environments."""
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


# ===================================
# Project Metadata
# ===================================

class ProjectMetadata(BaseModel):
    """Project metadata detected from user prompt."""
    language: ProjectLanguage
    project_type: str = Field(description="backend, frontend, fullstack")
    package_manager: str = Field(description="npm, pip, maven, etc.")


# ===================================
# GitHub Repository Schemas
# ===================================

class RepoCreateRequest(BaseModel):
    """Request to create a GitHub repository."""
    name: str = Field(..., description="Repository name")
    description: Optional[str] = Field(None, description="Repository description")
    private: bool = Field(False, description="Whether repo is private")
    auto_init: bool = Field(True, description="Initialize with README")


class RepoInfo(BaseModel):
    """GitHub repository information."""
    name: str
    full_name: str
    html_url: str
    clone_url: str
    default_branch: str
    private: bool
    created_at: Optional[datetime] = None


class BranchInfo(BaseModel):
    """Git branch information."""
    name: str
    commit_sha: str
    protected: bool = False


# ===================================
# Pull Request Schemas
# ===================================

class PRCreateRequest(BaseModel):
    """Request to create a pull request."""
    title: str = Field(..., description="PR title")
    body: str = Field(..., description="PR description")
    head: str = Field(..., description="Source branch")
    base: str = Field("main", description="Target branch")
    draft: bool = Field(False, description="Create as draft PR")
    reviewers: Optional[List[str]] = Field(None, description="Requested reviewers")


class PRInfo(BaseModel):
    """Pull request information."""
    number: int
    title: str
    body: Optional[str] = None
    state: str
    html_url: str
    head_branch: str
    base_branch: str
    mergeable: Optional[bool] = None
    merged: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PRMergeRequest(BaseModel):
    """Request to merge a pull request."""
    pr_number: int = Field(..., description="PR number to merge")
    merge_method: MergeMethod = Field(MergeMethod.SQUASH, description="Merge method")
    commit_title: Optional[str] = Field(None, description="Custom commit title")
    commit_message: Optional[str] = Field(None, description="Custom commit message")


class PRMergeResult(BaseModel):
    """Result of PR merge operation."""
    merged: bool
    sha: Optional[str] = None
    message: str


# ===================================
# GitHub Actions Schemas
# ===================================

class WorkflowTriggerRequest(BaseModel):
    """Request to trigger a GitHub Actions workflow."""
    workflow_id: str = Field(..., description="Workflow file name or ID")
    ref: str = Field("main", description="Git ref to run workflow on")
    inputs: Optional[Dict[str, Any]] = Field(None, description="Workflow inputs")


class WorkflowRunInfo(BaseModel):
    """GitHub Actions workflow run information."""
    id: int
    name: str
    status: str
    conclusion: Optional[str] = None
    html_url: str
    created_at: Optional[datetime] = None


# ===================================
# GitHub Secrets Schemas
# ===================================

class SecretCreateRequest(BaseModel):
    """Request to create a GitHub secret."""
    name: str = Field(..., description="Secret name")
    value: str = Field(..., description="Secret value")


class SecretInfo(BaseModel):
    """GitHub secret information (value not exposed)."""
    name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ===================================
# Git Operations Schemas
# ===================================

class CommitInfo(BaseModel):
    """Git commit information."""
    sha: str
    message: str
    author: str
    timestamp: Optional[datetime] = None


class FileContent(BaseModel):
    """File content for GitOps operations."""
    path: str = Field(..., description="File path in repository")
    content: str = Field(..., description="File content")


class GitPushRequest(BaseModel):
    """Request to push changes to remote."""
    branch: str = Field(..., description="Branch to push")
    commit_message: str = Field(..., description="Commit message")
    files: List[FileContent] = Field(..., description="Files to commit")


# ===================================
# DevOps Workflow Schemas
# ===================================

class DevOpsWorkflowRequest(BaseModel):
    """Request to start a DevOps workflow."""
    user_prompt: str = Field(..., description="User's project requirement")
    repo_name: str = Field(..., description="Repository name")
    target_environment: TargetEnvironment = Field(TargetEnvironment.DEV, description="Target environment")
    feature_branch: Optional[str] = Field(None, description="Feature branch name (optional)")
    approval_required: bool = Field(True, description="Require approval before merge")
    workflow_id: Optional[str] = Field(None, description="Resume existing workflow")


class DevOpsWorkflowState(BaseModel):
    """DevOps workflow state."""
    workflow_id: str
    user_prompt: str
    repo_name: str
    repo_url: Optional[str] = None
    target_environment: str
    current_state: WorkflowStep
    status: WorkflowStatus
    metadata: Optional[ProjectMetadata] = None
    branch_name: Optional[str] = None
    pr_url: Optional[str] = None
    pr_number: Optional[str] = None
    error: Optional[str] = None
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DevOpsWorkflowResult(BaseModel):
    """Result of DevOps workflow execution."""
    workflow_id: str
    status: WorkflowStatus
    current_state: WorkflowStep
    repo_url: Optional[str] = None
    pr_url: Optional[str] = None
    deployment_triggered: bool = False
    error: Optional[str] = None
    artifacts: Dict[str, Any] = Field(default_factory=dict)


# ===================================
# File Generation Schemas
# ===================================

class GeneratedFile(BaseModel):
    """Generated DevOps file."""
    path: str
    content: str
    file_type: str = Field(description="dockerfile, k8s, workflow, app, test, etc.")


class FileGenerationRequest(BaseModel):
    """Request to generate DevOps files."""
    user_prompt: str
    language: ProjectLanguage
    project_name: str
    target_environment: TargetEnvironment


class FileGenerationResult(BaseModel):
    """Result of file generation."""
    files: List[GeneratedFile]
    critic_approved: bool = False
    critic_feedback: Optional[List[str]] = None


# ===================================
# Deployment Schemas
# ===================================

class DeploymentRequest(BaseModel):
    """Request to trigger deployment."""
    repo_name: str
    environment: TargetEnvironment
    version: Optional[str] = Field(None, description="Version/tag to deploy")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Additional parameters")


class DeploymentStatus(BaseModel):
    """Deployment status information."""
    deployment_id: str
    environment: str
    status: str
    version: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


# ===================================
# API Response Schemas
# ===================================

class DevOpsResponse(BaseModel):
    """Standard DevOps API response."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class WorkflowListResponse(BaseModel):
    """List of workflows response."""
    workflows: List[DevOpsWorkflowState]
    total: int
