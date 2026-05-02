"""
Workflow State Store Service

PostgreSQL-backed state persistence for DevOps workflows.
Enables resume capability and multi-user support.
"""

import logging
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


class WorkflowStateStore:
    """
    PostgreSQL-backed workflow state store.
    
    Features:
    - Workflow creation and tracking
    - Step execution tracking
    - State snapshots for resume
    - Workflow resolution (find existing, create new)
    - Feature branch awareness
    - Multi-user support
    """
    
    async def create_workflow(
        self,
        repo_name: str,
        environment: str,
        intent: str,
        metadata: Dict[str, Any],
        created_by: str,
        current_state: str = "INIT",
        desired_state: str = "DEPLOYED",
        feature_branch: Optional[str] = None
    ) -> str:
        """
        Create new workflow.
        
        Args:
            repo_name: Repository name
            environment: Target environment
            intent: Workflow intent (deploy, build, rollback)
            metadata: Additional metadata
            created_by: User creating workflow
            current_state: Initial state
            desired_state: Target state
            feature_branch: Optional feature branch
            
        Returns:
            workflow_id
        """
        workflow_id = str(uuid.uuid4())
        
        async with AsyncSessionLocal() as db:
            try:
                # Insert workflow
                from app.models.models import Base
                
                # Use raw SQL for now (models will be added later)
                await db.execute(
                    """
                    INSERT INTO workflows (
                        id, repo_name, environment, intent,
                        current_state, desired_state, metadata,
                        created_by, feature_branch, status
                    ) VALUES (
                        :id, :repo_name, :environment, :intent,
                        :current_state, :desired_state, :metadata,
                        :created_by, :feature_branch, 'RUNNING'
                    )
                    """,
                    {
                        "id": workflow_id,
                        "repo_name": repo_name,
                        "environment": environment,
                        "intent": intent,
                        "current_state": current_state,
                        "desired_state": desired_state,
                        "metadata": metadata,
                        "created_by": created_by,
                        "feature_branch": feature_branch
                    }
                )
                
                # Create workflow access entry (owner role)
                access_id = str(uuid.uuid4())
                await db.execute(
                    """
                    INSERT INTO workflow_access (id, workflow_id, user_id, role)
                    VALUES (:id, :workflow_id, :user_id, 'owner')
                    """,
                    {
                        "id": access_id,
                        "workflow_id": workflow_id,
                        "user_id": created_by
                    }
                )
                
                await db.commit()
                
                logger.info(f"Created workflow: {workflow_id}")
                return workflow_id
                
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to create workflow: {e}")
                raise
    
    async def load_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Load workflow by ID."""
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    """
                    SELECT * FROM workflows WHERE id = :id
                    """,
                    {"id": workflow_id}
                )
                
                row = result.fetchone()
                if not row:
                    return None
                
                return dict(row._mapping)
                
            except Exception as e:
                logger.error(f"Failed to load workflow: {e}")
                return None
    
    async def save_state(
        self,
        workflow_id: str,
        state: Dict[str, Any]
    ):
        """Save workflow state snapshot."""
        async with AsyncSessionLocal() as db:
            try:
                # Extract fields
                current_state = state.get("current_state", "INIT")
                desired_state = state.get("desired_state", "DEPLOYED")
                status = state.get("status", "RUNNING")
                
                # Create state snapshot (exclude non-serializable fields)
                state_snapshot = {
                    k: v for k, v in state.items()
                    if k not in ["workflow_id", "created_by", "run_id"]
                    and v is not None
                    and not callable(v)
                }
                
                await db.execute(
                    """
                    UPDATE workflows
                    SET current_state = :current_state,
                        desired_state = :desired_state,
                        status = :status,
                        state_snapshot = :state_snapshot,
                        updated_at = NOW()
                    WHERE id = :id
                    """,
                    {
                        "id": workflow_id,
                        "current_state": current_state,
                        "desired_state": desired_state,
                        "status": status,
                        "state_snapshot": state_snapshot
                    }
                )
                
                await db.commit()
                
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to save state: {e}")
                raise
    
    async def start_step(
        self,
        workflow_id: str,
        step_name: str,
        input_data: Dict[str, Any],
        executed_by: str
    ) -> str:
        """Mark step as RUNNING."""
        step_id = str(uuid.uuid4())
        
        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    """
                    INSERT INTO workflow_steps (
                        id, workflow_id, step_name, status,
                        input, executed_by, started_at
                    ) VALUES (
                        :id, :workflow_id, :step_name, 'RUNNING',
                        :input, :executed_by, NOW()
                    )
                    """,
                    {
                        "id": step_id,
                        "workflow_id": workflow_id,
                        "step_name": step_name,
                        "input": input_data,
                        "executed_by": executed_by
                    }
                )
                
                await db.commit()
                return step_id
                
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to start step: {e}")
                raise
    
    async def finish_step(
        self,
        workflow_id: str,
        step_name: str,
        output_data: Dict[str, Any]
    ):
        """Mark step as SUCCESS."""
        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    """
                    UPDATE workflow_steps
                    SET status = 'SUCCESS',
                        output = :output,
                        finished_at = NOW()
                    WHERE workflow_id = :workflow_id
                      AND step_name = :step_name
                      AND status = 'RUNNING'
                    """,
                    {
                        "workflow_id": workflow_id,
                        "step_name": step_name,
                        "output": output_data
                    }
                )
                
                await db.commit()
                
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to finish step: {e}")
                raise
    
    async def fail_step(
        self,
        workflow_id: str,
        step_name: str,
        error: str
    ):
        """Mark step as FAILED."""
        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    """
                    UPDATE workflow_steps
                    SET status = 'FAILED',
                        error = :error,
                        finished_at = NOW()
                    WHERE workflow_id = :workflow_id
                      AND step_name = :step_name
                      AND status = 'RUNNING'
                    """,
                    {
                        "workflow_id": workflow_id,
                        "step_name": step_name,
                        "error": error
                    }
                )
                
                # Also update workflow status
                await db.execute(
                    """
                    UPDATE workflows
                    SET status = 'FAILED',
                        updated_at = NOW()
                    WHERE id = :id
                    """,
                    {"id": workflow_id}
                )
                
                await db.commit()
                
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to mark step as failed: {e}")
                raise
    
    async def find_workflows(
        self,
        repo_name: Optional[str] = None,
        environment: Optional[str] = None,
        intent: Optional[str] = None,
        status_in: Optional[List[str]] = None,
        feature_branch: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Find workflows matching criteria."""
        async with AsyncSessionLocal() as db:
            try:
                # Build query
                conditions = []
                params = {}
                
                if repo_name:
                    conditions.append("repo_name = :repo_name")
                    params["repo_name"] = repo_name
                
                if environment:
                    conditions.append("environment = :environment")
                    params["environment"] = environment
                
                if intent:
                    conditions.append("intent = :intent")
                    params["intent"] = intent
                
                if status_in:
                    placeholders = ", ".join(f":status_{i}" for i in range(len(status_in)))
                    conditions.append(f"status IN ({placeholders})")
                    for i, status in enumerate(status_in):
                        params[f"status_{i}"] = status
                
                # Feature branch filtering
                if feature_branch is None:
                    conditions.append("feature_branch IS NULL")
                else:
                    conditions.append("feature_branch = :feature_branch")
                    params["feature_branch"] = feature_branch
                
                where_clause = " AND ".join(conditions) if conditions else "TRUE"
                
                result = await db.execute(
                    f"""
                    SELECT * FROM workflows
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    """,
                    params
                )
                
                rows = result.fetchall()
                return [dict(row._mapping) for row in rows]
                
            except Exception as e:
                logger.error(f"Failed to find workflows: {e}")
                return []
    
    async def get_workflow_steps(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Get all steps for a workflow."""
        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(
                    """
                    SELECT * FROM workflow_steps
                    WHERE workflow_id = :workflow_id
                    ORDER BY started_at
                    """,
                    {"workflow_id": workflow_id}
                )
                
                rows = result.fetchall()
                return [dict(row._mapping) for row in rows]
                
            except Exception as e:
                logger.error(f"Failed to get workflow steps: {e}")
                return []


# Global instance
workflow_state_store = WorkflowStateStore()
