"""OpenAPI Bridge endpoints for MCP service."""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.core.security import MCPUser, PermissionChecker, get_current_user
from app.models.schemas import OpenAPIConversionRequest, OpenAPIConversionResult, OpenAPISpec
from app.services.openapi_bridge import openapi_bridge

router = APIRouter(prefix="/openapi", tags=["OpenAPI Bridge"])


@router.get("/specs", response_model=List[OpenAPISpec])
async def list_specs(
    user: MCPUser = Depends(get_current_user),
) -> List[OpenAPISpec]:
    """List all loaded OpenAPI specs."""
    return openapi_bridge.list_specs()


@router.post("/specs/load-url")
async def load_spec_from_url(
    url: str,
    user: MCPUser = Depends(PermissionChecker(["gateway:*"])),
) -> Dict[str, Any]:
    """Load an OpenAPI spec from a URL."""
    spec = await openapi_bridge.load_spec_from_url(url)
    if not spec:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to load spec from URL",
        )
    return spec.model_dump()


@router.post("/specs/load-file")
async def load_spec_from_file(
    file: UploadFile,
    user: MCPUser = Depends(PermissionChecker(["gateway:*"])),
) -> Dict[str, Any]:
    """Load an OpenAPI spec from an uploaded file."""
    import tempfile
    import os

    # Save uploaded file temporarily
    suffix = ".yaml" if file.filename.endswith((".yaml", ".yml")) else ".json"
    with tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        spec = await openapi_bridge.load_spec_from_file(tmp_path)
        if not spec:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to load spec from file",
            )
        return spec.model_dump()
    finally:
        os.unlink(tmp_path)


@router.post("/convert", response_model=OpenAPIConversionResult)
async def convert_spec_to_tools(
    request: OpenAPIConversionRequest,
    user: MCPUser = Depends(PermissionChecker(["gateway:*"])),
) -> OpenAPIConversionResult:
    """Convert an OpenAPI spec to MCP tools."""
    import json
    import yaml

    spec_data = None

    if request.spec_content:
        spec_data = request.spec_content
    elif request.spec_url:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(request.spec_url)
            response.raise_for_status()
            content = response.text
            if request.spec_url.endswith((".yaml", ".yml")):
                spec_data = yaml.safe_load(content)
            else:
                spec_data = json.loads(content)

    if not spec_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No spec content or URL provided",
        )

    result = openapi_bridge.convert_to_tools(
        spec_data=spec_data,
        server_id=request.server_id,
        include_paths=request.include_paths or None,
        exclude_paths=request.exclude_paths or None,
    )

    return result
