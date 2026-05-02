"""
Local File Manager Service

Handles local git operations on fixed local path: C:\\New Drive\\Testing\\Repo_directory
"""

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
import subprocess

import git
from git.exc import GitCommandError

logger = logging.getLogger(__name__)


class LocalFileManager:
    """
    Manages local file operations and git workflows.
    
    Features:
    - Clone repositories to fixed local path
    - Create and manage branches
    - Commit and push changes
    - Write generated files to disk
    - Clean up repositories
    
    CRITICAL: Uses fixed local path - NEVER ask user, NEVER change
    """
    
    # FIXED LOCAL PATH - Windows path mounted to container
    BASE_DIRECTORY = "/Users/sohamsarbadhikari/workstation/aegisops/aegisops-prod/repo_directory"
    
    def __init__(self):
        self.base_dir = Path(self.BASE_DIRECTORY)
        self._ensure_base_directory()
    
    def _ensure_base_directory(self):
        """Ensure base directory exists."""
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Base directory ready: {self.base_dir}")
        except Exception as e:
            logger.error(f"Failed to create base directory: {e}")
            raise
    
    def get_repo_path(self, repo_name: str) -> Path:
        """Get full path for repository."""
        return self.base_dir / repo_name
    
    async def clone_repository(
        self,
        repo_url: str,
        repo_name: str,
        github_username: str,
        github_token: str
    ) -> Dict[str, Any]:
        """
        Clone repository to local path.
        
        Args:
            repo_url: Repository URL
            repo_name: Repository name
            github_username: GitHub username
            github_token: GitHub PAT
            
        Returns:
            Dict with local_path, source (created/existing)
        """
        repo_path = self.get_repo_path(repo_name)
        
        logger.info(f"Cloning repository to: {repo_path}")
        
        # Check if repo already exists
        if repo_path.exists() and (repo_path / '.git').exists():
            try:
                existing_repo = git.Repo(repo_path)
                origin_url = existing_repo.remotes.origin.url
                
                # Verify it's the correct repo
                expected_url = repo_url.replace('https://', '').replace('http://', '')
                actual_url = origin_url.replace('https://', '').replace('http://', '').replace(f'{github_username}:{github_token}@', '')
                
                if expected_url in actual_url or actual_url in expected_url:
                    logger.info(f"Repository already exists at: {repo_path}")
                    return {
                        "local_path": str(repo_path),
                        "source": "existing",
                        "repo": existing_repo
                    }
                else:
                    logger.warning(f"Existing repo has different origin, will re-clone")
            except Exception as e:
                logger.warning(f"Invalid git repo at path, will re-clone: {e}")
        
        # Clean existing directory if needed
        if repo_path.exists():
            logger.info(f"Cleaning existing directory: {repo_path}")
            try:
                shutil.rmtree(repo_path)
            except Exception as e:
                logger.warning(f"Failed to remove directory: {e}")
                # Force removal with Linux commands
                import subprocess
                subprocess.run(['rm', '-rf', str(repo_path)], check=False)
            time.sleep(1)
        
        # Create directory
        repo_path.mkdir(parents=True, exist_ok=True)
        
        # Clone with authentication
        auth_url = repo_url.replace('https://', f'https://{github_username}:{github_token}@')
        
        try:
            repo = git.Repo.clone_from(auth_url, repo_path)
            logger.info(f"Repository cloned successfully")
            
            return {
                "local_path": str(repo_path),
                "source": "created",
                "repo": repo
            }
            
        except GitCommandError as e:
            logger.error(f"Git clone failed: {e}")
            raise
    
    async def create_branch(
        self,
        repo_path: str,
        branch_name: str,
        feature_branch: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create and checkout branch.
        
        Args:
            repo_path: Local repository path
            branch_name: Branch name to create
            feature_branch: Optional user-specified feature branch
            
        Returns:
            Dict with branch_name, source (created/existing)
        """
        repo = git.Repo(repo_path)
        
        # Use feature branch if specified, otherwise use provided branch_name
        target_branch = feature_branch or branch_name
        
        logger.info(f"Creating branch: {target_branch}")
        
        # Get all branches (local and remote)
        all_branches = [ref.name for ref in repo.branches]
        try:
            all_branches.extend([ref.name.replace('origin/', '') for ref in repo.remotes.origin.refs])
        except:
            pass
        
        # Check if branch exists
        if target_branch in all_branches:
            logger.info(f"Branch '{target_branch}' already exists, checking out...")
            try:
                repo.git.checkout(target_branch)
                return {
                    "branch_name": target_branch,
                    "source": "existing"
                }
            except:
                # Try to checkout from remote
                try:
                    repo.git.checkout('-b', target_branch, f'origin/{target_branch}')
                    return {
                        "branch_name": target_branch,
                        "source": "existing"
                    }
                except:
                    logger.warning(f"Could not checkout existing branch, creating new")
        
        # Create new branch from default branch
        try:
            repo.git.checkout('main')
        except:
            try:
                repo.git.checkout('master')
            except:
                logger.warning("Could not checkout main/master, using current branch")
        
        repo.git.checkout('-b', target_branch)
        
        logger.info(f"Branch created: {target_branch}")
        
        return {
            "branch_name": target_branch,
            "source": "created"
        }
    
    async def write_files(
        self,
        repo_path: str,
        files: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Write generated files to local repository.
        
        Args:
            repo_path: Local repository path
            files: Dict of {path: content}
            
        Returns:
            Dict with files_written count
        """
        repo_path_obj = Path(repo_path)
        files_written = 0
        
        logger.info(f"Writing {len(files)} files to: {repo_path}")
        
        for file_path, content in files.items():
            full_path = repo_path_obj / file_path
            
            # Create parent directories
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write file
            try:
                full_path.write_text(content, encoding='utf-8')
                files_written += 1
                logger.info(f"Written: {file_path}")
            except Exception as e:
                logger.error(f"Failed to write {file_path}: {e}")
        
        logger.info(f"Written {files_written}/{len(files)} files")
        
        return {
            "files_written": files_written,
            "total_files": len(files)
        }
    
    async def commit_and_push(
        self,
        repo_path: str,
        commit_message: str,
        branch_name: str
    ) -> Dict[str, Any]:
        """
        Commit changes and push to remote.
        
        Args:
            repo_path: Local repository path
            commit_message: Commit message
            branch_name: Branch to push
            
        Returns:
            Dict with commit_sha, changes_committed
        """
        repo = git.Repo(repo_path)
        
        logger.info(f"Committing changes to branch: {branch_name}")
        
        # Check if there are changes
        if not repo.is_dirty(untracked_files=True):
            logger.info("No changes to commit")
            return {
                "commit_sha": repo.head.commit.hexsha,
                "changes_committed": False,
                "source": "no_changes"
            }
        
        # Stage all changes
        repo.git.add(A=True)
        
        # Commit
        repo.index.commit(commit_message)
        commit_sha = repo.head.commit.hexsha
        
        logger.info(f"Changes committed: {commit_sha[:8]}")
        
        # Push to remote
        logger.info(f"Pushing branch {branch_name} to remote...")
        repo.remote('origin').push(refspec=f"{branch_name}:{branch_name}")
        
        logger.info("Changes pushed successfully")
        
        return {
            "commit_sha": commit_sha,
            "changes_committed": True,
            "source": "committed"
        }
    
    async def cleanup_repository(
        self,
        repo_name: str
    ) -> Dict[str, Any]:
        """
        Clean up local repository.
        
        Args:
            repo_name: Repository name
            
        Returns:
            Dict with cleanup status
        """
        repo_path = self.get_repo_path(repo_name)
        
        if not repo_path.exists():
            logger.info(f"Repository does not exist: {repo_path}")
            return {"cleaned": False, "reason": "not_found"}
        
        logger.info(f"Cleaning up repository: {repo_path}")
        
        try:
            shutil.rmtree(repo_path)
            logger.info("Repository cleaned up successfully")
            return {"cleaned": True}
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            # Try Linux-specific cleanup
            try:
                import subprocess
                subprocess.run(['rm', '-rf', str(repo_path)], 
                             check=True, capture_output=True)
                logger.info("Repository cleaned up successfully (Linux)")
                return {"cleaned": True}
            except:
                return {"cleaned": False, "error": str(e)}
    
    def get_base_directory(self) -> str:
        """Get the fixed base directory path."""
        return str(self.base_dir)


# Global instance
local_file_manager = LocalFileManager()
