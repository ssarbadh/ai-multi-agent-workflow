"""Workflow Registry Service - Dynamic workflow discovery and loading.

This service enables adding new service request workflows without code changes.
It discovers workflow JSON definitions at startup and on-demand, validates them,
and provides them to the provisioner agent.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import asyncio

# Optional watchdog for hot-reloading (not critical for demo)
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("watchdog not available - hot-reload disabled")

from app.schemas.workflow_schemas import (
    WorkflowDefinition,
    WorkflowRegistryEntry,
    WorkflowRegistryResponse,
    WorkflowType
)
from app.core.config import settings

logger = logging.getLogger(__name__)


if WATCHDOG_AVAILABLE:
    class WorkflowFileWatcher(FileSystemEventHandler):
        """Watches workflow directory for changes."""
        
        def __init__(self, registry: 'WorkflowRegistry'):
            self.registry = registry
            
        def on_modified(self, event):
            """Handle file modification events."""
            if event.is_directory:
                return
            if event.src_path.endswith('.json'):
                logger.info(f"Workflow file modified: {event.src_path}")
                # Reload the specific workflow
                asyncio.create_task(self.registry.reload_workflow(event.src_path))


class WorkflowRegistry:
    """
    Dynamic workflow registry that discovers and loads workflow definitions.
    
    Key features:
    - Loads workflows from JSON files at startup
    - Watches for file changes and auto-reloads
    - Validates workflow definitions
    - Provides query and lookup methods
    - No code changes needed to add new workflows
    """
    
    def __init__(self, workflows_dir: Optional[Path] = None):
        """
        Initialize workflow registry.
        
        Args:
            workflows_dir: Path to workflows directory
        """
        if workflows_dir is None:
            base_dir = Path(__file__).parent.parent.parent / "data" / "workflows"
            workflows_dir = base_dir / "templates"
        
        self.workflows_dir = Path(workflows_dir)
        self.workflows: Dict[str, WorkflowDefinition] = {}
        self.workflows_by_type: Dict[WorkflowType, List[str]] = {}
        self.workflows_by_category: Dict[str, List[str]] = {}
        self._observer: Optional[Observer] = None
        
        logger.info(f"Initializing workflow registry from: {self.workflows_dir}")
    
    async def initialize(self) -> None:
        """Initialize the registry by loading all workflows."""
        logger.info("Loading workflows from directory...")
        
        # Create directory if it doesn't exist
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        
        # Load all workflow files
        loaded_count = await self.load_all_workflows()
        
        logger.info(f"Successfully loaded {loaded_count} workflows")
        
        # Start file watcher
        self.start_watching()
    
    async def load_all_workflows(self) -> int:
        """
        Load all workflow definitions from JSON files.
        
        Returns:
            Number of workflows loaded
        """
        loaded_count = 0
        
        # Find all JSON files
        json_files = list(self.workflows_dir.glob("*.json"))
        
        for json_file in json_files:
            try:
                await self.load_workflow(json_file)
                loaded_count += 1
            except Exception as e:
                logger.error(f"Failed to load workflow from {json_file}: {e}")
        
        return loaded_count
    
    async def load_workflow(self, file_path: Path) -> WorkflowDefinition:
        """
        Load a single workflow definition from JSON file.
        
        Args:
            file_path: Path to workflow JSON file
            
        Returns:
            Loaded workflow definition
        """
        logger.info(f"Loading workflow from: {file_path}")
        
        with open(file_path, 'r') as f:
            workflow_data = json.load(f)
        
        # Validate and parse with Pydantic
        workflow = WorkflowDefinition(**workflow_data)
        
        # Store in registry
        self.workflows[workflow.workflow_id] = workflow
        
        # Index by type
        if workflow.workflow_type not in self.workflows_by_type:
            self.workflows_by_type[workflow.workflow_type] = []
        self.workflows_by_type[workflow.workflow_type].append(workflow.workflow_id)
        
        # Index by category
        if workflow.category not in self.workflows_by_category:
            self.workflows_by_category[workflow.category] = []
        self.workflows_by_category[workflow.category].append(workflow.workflow_id)
        
        logger.info(
            f"Loaded workflow: {workflow.workflow_id} "
            f"({workflow.name}, type={workflow.workflow_type}, "
            f"steps={len(workflow.steps)})"
        )
        
        return workflow
    
    async def reload_workflow(self, file_path: str) -> None:
        """
        Reload a workflow after file modification.
        
        Args:
            file_path: Path to modified workflow file
        """
        try:
            await self.load_workflow(Path(file_path))
            logger.info(f"Reloaded workflow from: {file_path}")
        except Exception as e:
            logger.error(f"Failed to reload workflow from {file_path}: {e}")
    
    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """
        Get workflow definition by ID.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            Workflow definition or None
        """
        return self.workflows.get(workflow_id)
    
    def get_workflows_by_type(
        self,
        workflow_type: WorkflowType
    ) -> List[WorkflowDefinition]:
        """
        Get all workflows of a specific type.
        
        Args:
            workflow_type: Type of workflow
            
        Returns:
            List of workflow definitions
        """
        workflow_ids = self.workflows_by_type.get(workflow_type, [])
        return [self.workflows[wid] for wid in workflow_ids if wid in self.workflows]
    
    def get_workflows_by_category(self, category: str) -> List[WorkflowDefinition]:
        """
        Get all workflows in a category.
        
        Args:
            category: Category name
            
        Returns:
            List of workflow definitions
        """
        workflow_ids = self.workflows_by_category.get(category, [])
        return [self.workflows[wid] for wid in workflow_ids if wid in self.workflows]
    
    def search_workflows(
        self,
        query: Optional[str] = None,
        workflow_type: Optional[WorkflowType] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> List[WorkflowDefinition]:
        """
        Search workflows by various criteria.
        
        Args:
            query: Text search in name/description
            workflow_type: Filter by workflow type
            category: Filter by category
            tags: Filter by tags (any match)
            
        Returns:
            List of matching workflows
        """
        results = list(self.workflows.values())
        
        # Filter by type
        if workflow_type:
            results = [w for w in results if w.workflow_type == workflow_type]
        
        # Filter by category
        if category:
            results = [w for w in results if w.category == category]
        
        # Filter by tags
        if tags:
            results = [
                w for w in results
                if any(tag in w.tags for tag in tags)
            ]
        
        # Text search
        if query:
            query_lower = query.lower()
            results = [
                w for w in results
                if query_lower in w.name.lower()
                or query_lower in w.description.lower()
                or query_lower in w.workflow_id.lower()
            ]
        
        return results
    
    def list_all_workflows(self) -> WorkflowRegistryResponse:
        """
        List all workflows in the registry.
        
        Returns:
            Registry response with all workflows
        """
        entries = []
        
        for workflow in self.workflows.values():
            entry = WorkflowRegistryEntry(
                workflow_id=workflow.workflow_id,
                name=workflow.name,
                workflow_type=workflow.workflow_type,
                category=workflow.category,
                version=workflow.version,
                description=workflow.description,
                tags=workflow.tags,
                parameters_count=len(workflow.parameters),
                steps_count=len(workflow.steps),
                estimated_duration_minutes=workflow.estimated_duration_minutes,
                requires_approval=workflow.requires_approval,
                file_path=str(self.workflows_dir / f"{workflow.workflow_id}.json")
            )
            entries.append(entry)
        
        categories = list(self.workflows_by_category.keys())
        
        return WorkflowRegistryResponse(
            total_workflows=len(entries),
            workflows=entries,
            categories=categories
        )
    
    def get_workflow_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about registered workflows.
        
        Returns:
            Statistics dictionary
        """
        total_steps = sum(len(w.steps) for w in self.workflows.values())
        avg_steps = total_steps / len(self.workflows) if self.workflows else 0
        
        total_duration = sum(
            w.estimated_duration_minutes for w in self.workflows.values()
        )
        avg_duration = total_duration / len(self.workflows) if self.workflows else 0
        
        return {
            "total_workflows": len(self.workflows),
            "total_steps": total_steps,
            "average_steps_per_workflow": round(avg_steps, 2),
            "average_duration_minutes": round(avg_duration, 2),
            "workflows_by_type": {
                str(k): len(v) for k, v in self.workflows_by_type.items()
            },
            "workflows_by_category": {
                k: len(v) for k, v in self.workflows_by_category.items()
            },
            "workflows_requiring_approval": sum(
                1 for w in self.workflows.values() if w.requires_approval
            )
        }
    
    def start_watching(self) -> None:
        """Start watching workflow directory for changes."""
        if not WATCHDOG_AVAILABLE:
            logger.info("Watchdog not available - skipping hot-reload setup")
            return
            
        try:
            event_handler = WorkflowFileWatcher(self)
            self._observer = Observer()
            self._observer.schedule(
                event_handler,
                str(self.workflows_dir),
                recursive=False
            )
            self._observer.start()
            logger.info(f"Started watching workflow directory: {self.workflows_dir}")
        except Exception as e:
            logger.error(f"Failed to start workflow directory watcher: {e}")
    
    def stop_watching(self) -> None:
        """Stop watching workflow directory."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            logger.info("Stopped watching workflow directory")
    
    async def validate_workflow(
        self,
        workflow: WorkflowDefinition
    ) -> Dict[str, Any]:
        """
        Validate a workflow definition.
        
        Args:
            workflow: Workflow to validate
            
        Returns:
            Validation result
        """
        errors = []
        warnings = []
        
        # Check step numbers are sequential
        step_numbers = [step.step for step in workflow.steps]
        expected_steps = list(range(1, len(workflow.steps) + 1))
        if step_numbers != expected_steps:
            errors.append(
                f"Step numbers not sequential: {step_numbers} "
                f"(expected {expected_steps})"
            )
        
        # Check dependencies reference valid steps
        for step in workflow.steps:
            for dep in step.dependencies:
                if dep not in step_numbers:
                    errors.append(
                        f"Step {step.step} has invalid dependency: {dep}"
                    )
        
        # Check estimated duration
        total_step_duration = sum(
            step.estimated_duration_seconds for step in workflow.steps
        )
        expected_minutes = (total_step_duration / 60)
        if abs(workflow.estimated_duration_minutes - expected_minutes) > 5:
            warnings.append(
                f"Workflow duration estimate ({workflow.estimated_duration_minutes} min) "
                f"differs from step total ({expected_minutes:.1f} min)"
            )
        
        # Check approval flags
        any_step_requires_approval = any(
            step.requires_approval for step in workflow.steps
        )
        if any_step_requires_approval and not workflow.requires_approval:
            errors.append(
                "Workflow has steps requiring approval but "
                "workflow.requires_approval is False"
            )
        
        is_valid = len(errors) == 0
        
        return {
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "workflow_id": workflow.workflow_id,
            "validated_at": datetime.utcnow().isoformat()
        }


# Global registry instance
_workflow_registry: Optional[WorkflowRegistry] = None


def get_workflow_registry() -> WorkflowRegistry:
    """
    Get the global workflow registry instance.
    
    Returns:
        WorkflowRegistry instance
    """
    global _workflow_registry
    if _workflow_registry is None:
        _workflow_registry = WorkflowRegistry()
    return _workflow_registry


async def initialize_workflow_registry() -> WorkflowRegistry:
    """
    Initialize the workflow registry.
    
    Returns:
        Initialized WorkflowRegistry
    """
    registry = get_workflow_registry()
    await registry.initialize()
    return registry
