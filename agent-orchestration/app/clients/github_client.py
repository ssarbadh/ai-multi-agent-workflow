"""Enhanced GitHub client for DevOps operations.

Per HLD: DevOps Agent – Interacts with Github for push, pull, merge, PR, reviews, github actions and gitops
"""

import base64
import logging
import re
from typing import Dict, Any, Optional, List

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class GitHubClientError(Exception):
    """GitHub API error."""
    def __init__(self, message: str, status_code: int = None, response: Dict = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(message)


class GitHubClient:
    """
    Enhanced GitHub client for DevOps operations.
    
    Supports:
    - Repository management (create, get, list)
    - Pull request operations (create, merge, list, review)
    - GitHub Actions (trigger workflows, get runs)
    - Secrets management (create, update, delete)
    - Branch operations (create, delete, protect)
    - File operations (create, update, delete)
    """
    
    # Sentinel value to detect when no argument was passed
    _NOT_PROVIDED = object()
    
    def __init__(
        self,
        token: str = _NOT_PROVIDED,
        username: str = _NOT_PROVIDED,
        org: str = None,
        base_url: str = "https://api.github.com"
    ):
        # Only use settings if argument was not provided at all
        # If explicitly passed as None, use empty string
        if token is self._NOT_PROVIDED:
            self.token = getattr(settings, 'GITHUB_TOKEN', '') or ''
        else:
            self.token = token or ''
            
        if username is self._NOT_PROVIDED:
            self.username = getattr(settings, 'GITHUB_USERNAME', '') or ''
        else:
            self.username = username or ''
            
        self.org = org or getattr(settings, 'GITHUB_ORG', None)
        self.base_url = base_url
        
        self.headers = {
            "Authorization": f"Bearer {self.token}" if self.token else "",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        self._client: Optional[httpx.AsyncClient] = None
    
    @property
    def is_configured(self) -> bool:
        """Check if client is properly configured."""
        return bool(self.token and self.username and self.token.strip() and self.username.strip())
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=30.0
            )
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        json: Dict = None,
        params: Dict = None
    ) -> Dict[str, Any]:
        """Make an API request."""
        client = await self._get_client()
        
        try:
            response = await client.request(
                method=method,
                url=endpoint,
                json=json,
                params=params
            )
            
            if response.status_code == 204:
                return {"success": True}
            
            data = response.json() if response.content else {}
            
            if response.status_code >= 400:
                raise GitHubClientError(
                    message=data.get("message", f"HTTP {response.status_code}"),
                    status_code=response.status_code,
                    response=data
                )
            
            return data
            
        except httpx.RequestError as e:
            logger.error(f"GitHub API request failed: {e}")
            raise GitHubClientError(f"Request failed: {e}")
    
    # ===================================
    # Repository Operations
    # ===================================
    
    async def get_repo(self, owner: str = None, repo: str = None) -> Dict[str, Any]:
        """Get repository information."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        return await self._request("GET", f"/repos/{owner}/{repo}")
    
    async def create_repo(
        self,
        name: str,
        description: str = None,
        private: bool = False,
        auto_init: bool = True
    ) -> Dict[str, Any]:
        """Create a new repository."""
        logger.info(f"Creating repository: {name}")
        
        return await self._request(
            "POST",
            "/user/repos",
            json={
                "name": name,
                "description": description or f"DevOps automated project: {name}",
                "private": private,
                "auto_init": auto_init
            }
        )
    
    async def repo_exists(self, owner: str = None, repo: str = None) -> bool:
        """Check if repository exists."""
        try:
            await self.get_repo(owner, repo)
            return True
        except GitHubClientError as e:
            if e.status_code == 404:
                return False
            raise
    
    async def list_repos(self, per_page: int = 30, page: int = 1) -> List[Dict[str, Any]]:
        """List user's repositories."""
        return await self._request(
            "GET",
            "/user/repos",
            params={"per_page": per_page, "page": page, "sort": "updated"}
        )
    
    # ===================================
    # Pull Request Operations
    # ===================================
    
    async def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        owner: str = None,
        repo: str = None,
        draft: bool = False
    ) -> Dict[str, Any]:
        """Create a pull request."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        logger.info(f"Creating PR: {title} ({head} -> {base})")
        
        try:
            result = await self._request(
                "POST",
                f"/repos/{owner}/{repo}/pulls",
                json={
                    "title": title,
                    "body": body,
                    "head": head,
                    "base": base,
                    "draft": draft
                }
            )
            
            logger.info(f"Created PR #{result['number']}: {title}")
            return {
                "number": result["number"],
                "title": result["title"],
                "html_url": result["html_url"],
                "state": result["state"],
                "head_branch": result["head"]["ref"],
                "base_branch": result["base"]["ref"]
            }
            
        except GitHubClientError as e:
            # Try with master if main doesn't exist
            if e.status_code == 422 and base == "main":
                logger.info("Retrying PR creation with 'master' base branch")
                return await self.create_pull_request(
                    title=title,
                    body=body,
                    head=head,
                    base="master",
                    owner=owner,
                    repo=repo,
                    draft=draft
                )
            raise
    
    async def merge_pull_request(
        self,
        pr_number: int,
        merge_method: str = "squash",
        commit_title: str = None,
        commit_message: str = None,
        owner: str = None,
        repo: str = None
    ) -> Dict[str, Any]:
        """Merge a pull request."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        logger.info(f"Merging PR #{pr_number} using {merge_method}")
        
        payload = {"merge_method": merge_method}
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message
        
        result = await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/merge",
            json=payload
        )
        
        logger.info(f"Merged PR #{pr_number}")
        return {
            "merged": result.get("merged", True),
            "sha": result.get("sha"),
            "message": result.get("message", "PR merged successfully")
        }
    
    async def list_pull_requests(
        self,
        state: str = "open",
        owner: str = None,
        repo: str = None,
        per_page: int = 30
    ) -> List[Dict[str, Any]]:
        """List pull requests."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": per_page}
        )
    
    async def get_pull_request(
        self,
        pr_number: int,
        owner: str = None,
        repo: str = None
    ) -> Dict[str, Any]:
        """Get pull request details."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}"
        )
    
    async def find_pr_by_branch(
        self,
        branch: str,
        owner: str = None,
        repo: str = None
    ) -> Optional[Dict[str, Any]]:
        """Find open PR for a branch."""
        prs = await self.list_pull_requests(state="open", owner=owner, repo=repo)
        
        for pr in prs:
            if pr["head"]["ref"] == branch:
                return pr
        
        return None
    
    # ===================================
    # GitHub Actions Operations
    # ===================================
    
    async def trigger_workflow(
        self,
        workflow_id: str,
        ref: str = "main",
        inputs: Dict[str, Any] = None,
        owner: str = None,
        repo: str = None
    ) -> Dict[str, Any]:
        """Trigger a GitHub Actions workflow."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        logger.info(f"Triggering workflow: {workflow_id} on {ref}")
        
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches",
            json={
                "ref": ref,
                "inputs": inputs or {}
            }
        )
        
        return {"status": "triggered", "workflow_id": workflow_id, "ref": ref}
    
    async def list_workflow_runs(
        self,
        workflow_id: str = None,
        owner: str = None,
        repo: str = None,
        per_page: int = 10
    ) -> List[Dict[str, Any]]:
        """List workflow runs."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        endpoint = f"/repos/{owner}/{repo}/actions/runs"
        if workflow_id:
            endpoint = f"/repos/{owner}/{repo}/actions/workflows/{workflow_id}/runs"
        
        result = await self._request(
            "GET",
            endpoint,
            params={"per_page": per_page}
        )
        
        return result.get("workflow_runs", [])
    
    async def get_workflow_run(
        self,
        run_id: int,
        owner: str = None,
        repo: str = None
    ) -> Dict[str, Any]:
        """Get workflow run details."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs/{run_id}"
        )
    
    # ===================================
    # Secrets Operations
    # ===================================
    
    async def get_repo_public_key(
        self,
        owner: str = None,
        repo: str = None
    ) -> Dict[str, str]:
        """Get repository public key for encrypting secrets."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/secrets/public-key"
        )
    
    async def create_or_update_secret(
        self,
        secret_name: str,
        secret_value: str,
        owner: str = None,
        repo: str = None
    ) -> Dict[str, Any]:
        """Create or update a repository secret."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        # Get public key for encryption
        public_key = await self.get_repo_public_key(owner, repo)
        
        # Encrypt the secret value
        encrypted_value = self._encrypt_secret(secret_value, public_key["key"])
        
        logger.info(f"Creating/updating secret: {secret_name}")
        
        await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/actions/secrets/{secret_name}",
            json={
                "encrypted_value": encrypted_value,
                "key_id": public_key["key_id"]
            }
        )
        
        return {"name": secret_name, "status": "created"}
    
    def _encrypt_secret(self, secret_value: str, public_key: str) -> str:
        """Encrypt a secret value using the repository's public key."""
        try:
            from nacl import encoding, public
            
            public_key_obj = public.PublicKey(
                public_key.encode("utf-8"),
                encoding.Base64Encoder()
            )
            sealed_box = public.SealedBox(public_key_obj)
            encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
            
            return base64.b64encode(encrypted).decode("utf-8")
            
        except ImportError:
            logger.warning("PyNaCl not installed, cannot encrypt secrets")
            raise GitHubClientError("PyNaCl required for secret encryption")
    
    async def list_secrets(
        self,
        owner: str = None,
        repo: str = None
    ) -> List[Dict[str, Any]]:
        """List repository secrets (names only, not values)."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        result = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/secrets"
        )
        
        return result.get("secrets", [])
    
    # ===================================
    # Branch Operations
    # ===================================
    
    async def list_branches(
        self,
        owner: str = None,
        repo: str = None,
        per_page: int = 100
    ) -> List[Dict[str, Any]]:
        """List repository branches."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/branches",
            params={"per_page": per_page}
        )
    
    async def get_branch(
        self,
        branch: str,
        owner: str = None,
        repo: str = None
    ) -> Dict[str, Any]:
        """Get branch details."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/branches/{branch}"
        )
    
    async def branch_exists(
        self,
        branch: str,
        owner: str = None,
        repo: str = None
    ) -> bool:
        """Check if branch exists."""
        try:
            await self.get_branch(branch, owner, repo)
            return True
        except GitHubClientError as e:
            if e.status_code == 404:
                return False
            raise
    
    # ===================================
    # File Operations
    # ===================================
    
    async def get_file_content(
        self,
        path: str,
        ref: str = None,
        owner: str = None,
        repo: str = None
    ) -> Dict[str, Any]:
        """Get file content from repository."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        params = {}
        if ref:
            params["ref"] = ref
        
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path}",
            params=params
        )
    
    async def create_or_update_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: str = None,
        owner: str = None,
        repo: str = None
    ) -> Dict[str, Any]:
        """Create or update a file in the repository."""
        owner = owner or self.username
        repo = repo or getattr(settings, 'GITHUB_REPO', None)
        
        # Encode content to base64
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        
        payload = {
            "message": message,
            "content": encoded_content
        }
        
        if branch:
            payload["branch"] = branch
        
        # Check if file exists to get SHA for update
        try:
            existing = await self.get_file_content(path, ref=branch, owner=owner, repo=repo)
            payload["sha"] = existing["sha"]
        except GitHubClientError as e:
            if e.status_code != 404:
                raise
        
        logger.info(f"Creating/updating file: {path}")
        
        return await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{path}",
            json=payload
        )
    
    # ===================================
    # Utility Methods
    # ===================================
    
    @staticmethod
    def extract_repo_name(repo_url: str) -> str:
        """Extract owner/repo from GitHub URL."""
        match = re.search(r'github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$', repo_url)
        if match:
            return match.group(1)
        raise ValueError(f"Invalid GitHub URL: {repo_url}")
    
    def get_auth_url(self, repo_url: str) -> str:
        """Get authenticated clone URL."""
        return repo_url.replace(
            "https://",
            f"https://{self.username}:{self.token}@"
        )


# Global instance
github_client = GitHubClient()
