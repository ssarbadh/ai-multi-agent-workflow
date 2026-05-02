"""Dynamic form generation service for collecting missing parameters."""

import logging
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from enum import Enum

logger = logging.getLogger(__name__)


class FieldType(str, Enum):
    """Form field types."""
    TEXT = "text"
    NUMBER = "number"
    SELECT = "select"
    MULTISELECT = "multiselect"
    TEXTAREA = "textarea"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"


class FormField(BaseModel):
    """Form field definition."""
    name: str
    label: str
    type: FieldType
    required: bool = True
    default: Optional[Any] = None
    options: Optional[List[str]] = None
    validation: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    placeholder: Optional[str] = None
    help_text: Optional[str] = None


class FormSchema(BaseModel):
    """Complete form schema."""
    form_id: str
    title: str
    description: Optional[str] = None
    fields: List[FormField]
    submit_label: str = "Submit"
    cancel_label: str = "Cancel"
    context: Optional[Dict[str, Any]] = None  # Original request context


class FormGenerator:
    """Generate dynamic forms from workflow definitions and missing parameters."""
    
    @staticmethod
    def generate_from_workflow(
        workflow_id: str,
        workflow_name: str,
        parameters: List[Any],  # Can be List[Dict] or List[WorkflowParameter]
        provided_params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[FormSchema]:
        """
        Generate form for missing workflow parameters.
        
        Args:
            workflow_id: Workflow identifier
            workflow_name: Human-readable workflow name
            parameters: Workflow parameter definitions (dict or Pydantic model)
            provided_params: Parameters already provided by user
            context: Additional context to include
            
        Returns:
            FormSchema if there are missing required parameters, None otherwise
        """
        missing_fields = []
        
        for param in parameters:
            # Handle both dict and Pydantic model
            if isinstance(param, dict):
                param_name = param.get("name")
                param_required = param.get("required", False)
                has_default = "default" in param
            else:
                # Pydantic model
                param_name = param.name
                param_required = param.required
                has_default = param.default is not None
            
            # Skip if parameter is already provided
            if param_name in provided_params:
                continue
            
            # Skip if parameter is optional and has a default
            if not param_required and has_default:
                continue
            
            # Only include required parameters or optional ones without defaults
            if param_required:
                field = FormGenerator._param_to_field(param)
                if field:
                    missing_fields.append(field)
        
        if not missing_fields:
            return None
        
        form_id = f"{workflow_id}_params"
        title = f"{workflow_name} - Required Parameters"
        description = "Please provide the following required parameters to continue:"
        
        return FormSchema(
            form_id=form_id,
            title=title,
            description=description,
            fields=missing_fields,
            context=context or {}
        )
    
    @staticmethod
    def _param_to_field(param: Any) -> Optional[FormField]:
        """Convert workflow parameter definition to form field."""
        # Handle both dict and Pydantic model
        if isinstance(param, dict):
            param_name = param.get("name")
            param_type = param.get("type", "str")
            param_desc = param.get("description", "")
            param_required = param.get("required", False)
            param_default = param.get("default")
            validation = param.get("validation", {})
        else:
            # Pydantic model
            param_name = param.name
            param_type = param.type
            param_desc = param.description or ""
            param_required = param.required
            param_default = param.default
            validation = param.validation or {}
        
        # Determine field type
        field_type = FieldType.TEXT
        options = None
        
        if param_type in ["int", "integer", "float", "number"]:
            field_type = FieldType.NUMBER
        elif param_type == "bool" or param_type == "boolean":
            field_type = FieldType.BOOLEAN
        elif "enum" in validation:
            # If enum is present, use SELECT or MULTISELECT based on type
            field_type = FieldType.SELECT
            options = validation["enum"]
            if param_type == "list[str]" or param_type.startswith("list"):
                field_type = FieldType.MULTISELECT
        elif param_type == "list[str]" or param_type.startswith("list"):
            # List without enum options - use TEXTAREA for comma-separated input
            field_type = FieldType.TEXTAREA
        elif param_type == "str" and param_name in ["description", "details", "notes", "comment"]:
            field_type = FieldType.TEXTAREA
        
        # Generate label from name
        label = param_name.replace("_", " ").title()
        
        # Generate placeholder
        placeholder = None
        if field_type == FieldType.TEXT:
            placeholder = f"Enter {label.lower()}"
        elif field_type == FieldType.NUMBER:
            placeholder = f"Enter {label.lower()}"
        elif field_type == FieldType.SELECT:
            placeholder = f"Select {label.lower()}"
        elif field_type == FieldType.MULTISELECT:
            placeholder = f"Select one or more {label.lower()}"
        elif field_type == FieldType.TEXTAREA and (param_type == "list[str]" or param_type.startswith("list")):
            placeholder = f"Enter {label.lower()} separated by commas (e.g., subnet-abc123, subnet-def456)"
        
        # Add help text from validation
        help_text = None
        if "pattern" in validation:
            help_text = f"Pattern: {validation['pattern']}"
        elif "ge" in validation and "le" in validation:
            help_text = f"Range: {validation['ge']} - {validation['le']}"
        elif "min_length" in validation:
            help_text = f"Minimum length: {validation['min_length']}"
        elif field_type == FieldType.TEXTAREA and (param_type == "list[str]" or param_type.startswith("list")):
            help_text = "Enter multiple values separated by commas"
        
        return FormField(
            name=param_name,
            label=label,
            type=field_type,
            required=param_required,
            default=param_default,
            options=options,
            validation=validation,
            description=param_desc,
            placeholder=placeholder,
            help_text=help_text
        )
    
    @staticmethod
    def generate_for_devops(
        action: str,
        provided_params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[FormSchema]:
        """Generate form for DevOps requests."""
        fields = []
        
        # Common fields for all DevOps actions
        if "repository" not in provided_params:
            fields.append(FormField(
                name="repository",
                label="Repository",
                type=FieldType.TEXT,
                required=True,
                placeholder="e.g., owner/repo",
                description="GitHub repository in format owner/repo"
            ))
        
        if "branch" not in provided_params:
            fields.append(FormField(
                name="branch",
                label="Branch",
                type=FieldType.TEXT,
                required=False,
                default="main",
                placeholder="e.g., main, develop",
                description="Git branch name"
            ))
        
        # Action-specific fields
        if action in ["deploy", "deployment"]:
            if "environment" not in provided_params:
                fields.append(FormField(
                    name="environment",
                    label="Environment",
                    type=FieldType.SELECT,
                    required=True,
                    options=["dev", "staging", "production"],
                    description="Deployment environment"
                ))
        
        if action in ["pr", "pull_request", "merge_request"]:
            if "title" not in provided_params:
                fields.append(FormField(
                    name="title",
                    label="PR Title",
                    type=FieldType.TEXT,
                    required=True,
                    placeholder="Brief description of changes"
                ))
            if "description" not in provided_params:
                fields.append(FormField(
                    name="description",
                    label="Description",
                    type=FieldType.TEXTAREA,
                    required=False,
                    placeholder="Detailed description of changes"
                ))
        
        if not fields:
            return None
        
        return FormSchema(
            form_id=f"devops_{action}_params",
            title=f"DevOps {action.title()} - Required Parameters",
            description="Please provide the following details:",
            fields=fields,
            context=context or {}
        )
    
    @staticmethod
    def generate_for_servicenow(
        ticket_type: str,
        provided_params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[FormSchema]:
        """Generate form for ServiceNow ticket creation."""
        fields = []
        
        if "short_description" not in provided_params:
            fields.append(FormField(
                name="short_description",
                label="Short Description",
                type=FieldType.TEXT,
                required=True,
                placeholder="Brief summary of the issue",
                description="One-line summary"
            ))
        
        if "description" not in provided_params:
            fields.append(FormField(
                name="description",
                label="Description",
                type=FieldType.TEXTAREA,
                required=False,
                placeholder="Detailed description of the issue",
                description="Full details"
            ))
        
        if "priority" not in provided_params:
            fields.append(FormField(
                name="priority",
                label="Priority",
                type=FieldType.SELECT,
                required=True,
                options=["1 - Critical", "2 - High", "3 - Moderate", "4 - Low"],
                default="3 - Moderate",
                description="Issue priority"
            ))
        
        if "urgency" not in provided_params:
            fields.append(FormField(
                name="urgency",
                label="Urgency",
                type=FieldType.SELECT,
                required=True,
                options=["1 - High", "2 - Medium", "3 - Low"],
                default="2 - Medium",
                description="How urgent is this?"
            ))
        
        if "category" not in provided_params:
            fields.append(FormField(
                name="category",
                label="Category",
                type=FieldType.SELECT,
                required=False,
                options=["Hardware", "Software", "Network", "Inquiry", "Other"],
                description="Issue category"
            ))
        
        if not fields:
            return None
        
        return FormSchema(
            form_id=f"servicenow_{ticket_type}_params",
            title=f"ServiceNow {ticket_type.upper()} - Required Information",
            description="Please provide the following ticket details:",
            fields=fields,
            context=context or {}
        )
    
    @staticmethod
    def generate_for_incident(
        provided_params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[FormSchema]:
        """Generate form for incident analysis."""
        fields = []
        
        if "time_range" not in provided_params:
            fields.append(FormField(
                name="time_range",
                label="Time Range",
                type=FieldType.SELECT,
                required=True,
                options=["Last 1 hour", "Last 6 hours", "Last 24 hours", "Last 7 days", "Custom"],
                default="Last 24 hours",
                description="Time period to analyze"
            ))
        
        if "severity" not in provided_params:
            fields.append(FormField(
                name="severity",
                label="Severity Filter",
                type=FieldType.MULTISELECT,
                required=False,
                options=["critical", "high", "medium", "low"],
                description="Filter by severity levels"
            ))
        
        if "service" not in provided_params:
            fields.append(FormField(
                name="service",
                label="Service/Component",
                type=FieldType.TEXT,
                required=False,
                placeholder="e.g., api-gateway, database",
                description="Specific service to analyze"
            ))
        
        if not fields:
            return None
        
        return FormSchema(
            form_id="incident_analysis_params",
            title="Incident Analysis - Parameters",
            description="Please specify the analysis parameters:",
            fields=fields,
            context=context or {}
        )
