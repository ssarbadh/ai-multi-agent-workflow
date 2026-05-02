"""Dynamic Pydantic model generator for workflow parameters.

This utility generates Pydantic models on-the-fly from workflow parameter definitions,
enabling dynamic validation without hardcoding schemas.
"""

import logging
from typing import Dict, Any, Type, Optional, List
from pydantic import BaseModel, Field, create_model, ConfigDict
from enum import Enum

from app.schemas.workflow_schemas import WorkflowDefinition, WorkflowParameter

logger = logging.getLogger(__name__)


class DynamicModelGenerator:
    """
    Generates Pydantic models dynamically from workflow parameter definitions.
    
    This allows workflows to define their own input schemas without modifying
    the codebase. The generated models provide full Pydantic validation.
    """
    
    # Type mapping from string to Python types
    TYPE_MAPPING = {
        "str": str,
        "string": str,
        "int": int,
        "integer": int,
        "float": float,
        "bool": bool,
        "boolean": bool,
        "dict": dict,
        "list": list,
        "any": Any,
    }
    
    def __init__(self):
        self._model_cache: Dict[str, Type[BaseModel]] = {}
    
    def generate_model(
        self,
        workflow: WorkflowDefinition,
        model_name: Optional[str] = None
    ) -> Type[BaseModel]:
        """
        Generate a Pydantic model from workflow parameter definitions.
        
        Args:
            workflow: Workflow definition
            model_name: Optional custom model name
            
        Returns:
            Generated Pydantic model class
        """
        if model_name is None:
            model_name = f"{workflow.workflow_id}_RequestModel"
        
        # Check cache
        if model_name in self._model_cache:
            return self._model_cache[model_name]
        
        logger.info(f"Generating dynamic model: {model_name}")
        
        # Build field definitions
        fields = {}
        
        for param in workflow.parameters:
            field_def = self._create_field_definition(param)
            fields[param.name] = field_def
        
        # Create the model
        model = create_model(
            model_name,
            __config__=ConfigDict(extra="allow"),
            **fields
        )
        
        # Cache the model
        self._model_cache[model_name] = model
        
        logger.info(
            f"Generated model {model_name} with {len(fields)} fields"
        )
        
        return model
    
    def _create_field_definition(
        self,
        param: WorkflowParameter
    ) -> tuple:
        """
        Create a Pydantic field definition from parameter definition.
        
        Args:
            param: Workflow parameter
            
        Returns:
            Tuple of (type, Field) for Pydantic model
        """
        # Get base type
        param_type = self._parse_type(param.type)
        
        # Handle optional (not required)
        if not param.required:
            param_type = Optional[param_type]
        
        # Create Field with metadata
        field_kwargs = {
            "description": param.description or param.name
        }
        
        # Add default if specified
        if param.default is not None:
            field_kwargs["default"] = param.default
        elif not param.required:
            field_kwargs["default"] = None
        else:
            # Required field with no default uses ellipsis
            field_kwargs["default"] = ...
        
        # Add validation rules if specified
        if param.validation:
            self._add_validation_rules(field_kwargs, param.validation, param_type)
        
        field = Field(**field_kwargs)
        
        return (param_type, field)
    
    def _parse_type(self, type_str: str) -> Type:
        """
        Parse type string to Python type.
        
        Args:
            type_str: Type as string (e.g., "str", "int", "List[str]")
            
        Returns:
            Python type
        """
        # Handle basic types
        type_lower = type_str.lower().strip()
        
        if type_lower in self.TYPE_MAPPING:
            return self.TYPE_MAPPING[type_lower]
        
        # Handle List types
        if type_lower.startswith("list["):
            inner_type_str = type_lower[5:-1]  # Extract inner type
            inner_type = self._parse_type(inner_type_str)
            return List[inner_type]
        
        # Handle Dict types
        if type_lower.startswith("dict["):
            # For simplicity, return Dict[str, Any]
            return Dict[str, Any]
        
        # Default to Any for unknown types
        logger.warning(f"Unknown type '{type_str}', using Any")
        return Any
    
    def _add_validation_rules(
        self,
        field_kwargs: Dict[str, Any],
        validation: Dict[str, Any],
        param_type: Type
    ) -> None:
        """
        Add validation rules to field definition.
        
        Args:
            field_kwargs: Field kwargs to modify
            validation: Validation rules dictionary
            param_type: Parameter type
        """
        # String validations
        if "min_length" in validation:
            field_kwargs["min_length"] = validation["min_length"]
        if "max_length" in validation:
            field_kwargs["max_length"] = validation["max_length"]
        if "pattern" in validation:
            field_kwargs["pattern"] = validation["pattern"]
        
        # Numeric validations
        if "ge" in validation:  # greater than or equal
            field_kwargs["ge"] = validation["ge"]
        if "gt" in validation:  # greater than
            field_kwargs["gt"] = validation["gt"]
        if "le" in validation:  # less than or equal
            field_kwargs["le"] = validation["le"]
        if "lt" in validation:  # less than
            field_kwargs["lt"] = validation["lt"]
        
        # List validations
        if "min_items" in validation:
            field_kwargs["min_items"] = validation["min_items"]
        if "max_items" in validation:
            field_kwargs["max_items"] = validation["max_items"]
    
    def validate_input(
        self,
        workflow: WorkflowDefinition,
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate input data against workflow parameter schema.
        
        Args:
            workflow: Workflow definition
            input_data: Input data to validate
            
        Returns:
            Validated and parsed data
            
        Raises:
            ValidationError: If validation fails
        """
        model = self.generate_model(workflow)
        
        # Validate using Pydantic
        validated = model(**input_data)
        
        # Return as dict
        return validated.model_dump()
    
    def get_json_schema(
        self,
        workflow: WorkflowDefinition
    ) -> Dict[str, Any]:
        """
        Get JSON schema for workflow parameters.
        
        Args:
            workflow: Workflow definition
            
        Returns:
            JSON schema dictionary
        """
        model = self.generate_model(workflow)
        return model.model_json_schema()
    
    def clear_cache(self) -> None:
        """Clear the model cache."""
        self._model_cache.clear()
        logger.info("Cleared dynamic model cache")


# Global generator instance
_model_generator: Optional[DynamicModelGenerator] = None


def get_model_generator() -> DynamicModelGenerator:
    """
    Get the global dynamic model generator instance.
    
    Returns:
        DynamicModelGenerator instance
    """
    global _model_generator
    if _model_generator is None:
        _model_generator = DynamicModelGenerator()
    return _model_generator


def generate_workflow_model(
    workflow: WorkflowDefinition
) -> Type[BaseModel]:
    """
    Generate Pydantic model for workflow.
    
    Args:
        workflow: Workflow definition
        
    Returns:
        Generated Pydantic model
    """
    generator = get_model_generator()
    return generator.generate_model(workflow)


def validate_workflow_input(
    workflow: WorkflowDefinition,
    input_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate input data for workflow.
    
    Args:
        workflow: Workflow definition
        input_data: Input data
        
    Returns:
        Validated data
    """
    generator = get_model_generator()
    return generator.validate_input(workflow, input_data)
