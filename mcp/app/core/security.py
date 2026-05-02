"""Security utilities for MCP service - API keys, JWT, RBAC."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import logger


api_key_header = APIKeyHeader(name=settings.API_KEY_HEADER, auto_error=False)


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str
    exp: int
    iat: int
    tenant_id: Optional[str] = None
    roles: List[str] = []
    permissions: List[str] = []


class MCPUser(BaseModel):
    """Authenticated MCP user/client."""

    id: str
    tenant_id: Optional[str] = None
    roles: Set[str] = set()
    permissions: Set[str] = set()
    api_key_hash: Optional[str] = None


# Role to permissions mapping
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    "admin": {
        "tools:*",
        "resources:*",
        "prompts:*",
        "sessions:*",
        "gateway:*",
        "audit:read",
    },
    "operator": {
        "tools:execute",
        "tools:list",
        "resources:read",
        "prompts:read",
        "sessions:create",
        "sessions:read",
    },
    "viewer": {
        "tools:list",
        "resources:read",
        "prompts:read",
    },
    "service": {
        "tools:execute",
        "tools:list",
        "resources:read",
    },
}


def hash_api_key(api_key: str) -> str:
    """Hash an API key for storage/comparison."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"mcp-{secrets.token_urlsafe(32)}"


def verify_api_key(api_key: str) -> bool:
    """Verify an API key against configured keys."""
    if not settings.API_KEYS:
        return True  # No keys configured = allow all (dev mode)
    return api_key in settings.API_KEYS


def create_access_token(
    subject: str,
    tenant_id: Optional[str] = None,
    roles: List[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRY_MINUTES)

    roles = roles or ["viewer"]
    permissions = []
    for role in roles:
        if role in ROLE_PERMISSIONS:
            permissions.extend(ROLE_PERMISSIONS[role])

    to_encode = {
        "sub": subject,
        "exp": int(expire.timestamp()),
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "tenant_id": tenant_id,
        "roles": roles,
        "permissions": list(set(permissions)),
    }

    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> TokenPayload:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return TokenPayload(**payload)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )


def get_permissions_for_roles(roles: List[str]) -> Set[str]:
    """Get all permissions for a list of roles."""
    permissions = set()
    for role in roles:
        role_lower = role.lower()
        if role_lower in ROLE_PERMISSIONS:
            permissions.update(ROLE_PERMISSIONS[role_lower])
    return permissions


async def get_current_user(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header),
) -> MCPUser:
    """Get current authenticated user from API key or JWT."""
    # Try API key first
    if api_key:
        if verify_api_key(api_key):
            logger.auth_event("api_key_auth", success=True)
            return MCPUser(
                id=f"apikey-{hash_api_key(api_key)[:8]}",
                roles={"operator"},
                permissions=get_permissions_for_roles(["operator"]),
                api_key_hash=hash_api_key(api_key),
            )
        else:
            logger.auth_event("api_key_auth", success=False)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

    # Try JWT from Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = decode_token(token)
        logger.auth_event("jwt_auth", user_id=payload.sub, success=True)
        return MCPUser(
            id=payload.sub,
            tenant_id=payload.tenant_id,
            roles=set(payload.roles),
            permissions=set(payload.permissions),
        )

    # Dev mode: allow anonymous with viewer permissions
    if settings.DEBUG and settings.ENVIRONMENT == "development":
        return MCPUser(
            id="anonymous",
            roles={"viewer"},
            permissions=get_permissions_for_roles(["viewer"]),
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


async def get_current_user_optional(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header),
) -> Optional[MCPUser]:
    """Get current user if authenticated, None otherwise."""
    try:
        return await get_current_user(request, api_key)
    except HTTPException:
        return None


def check_permission(user: MCPUser, required_permission: str) -> bool:
    """Check if user has a specific permission."""
    if "tools:*" in user.permissions or "resources:*" in user.permissions:
        return True

    # Check exact match
    if required_permission in user.permissions:
        return True

    # Check wildcard patterns
    parts = required_permission.split(":")
    if len(parts) == 2:
        wildcard = f"{parts[0]}:*"
        if wildcard in user.permissions:
            return True

    return False


def check_tool_permission(user: MCPUser, tool_id: str) -> bool:
    """Check if user can execute a specific tool."""
    # Check tool-specific permissions from config
    for pattern, roles_str in settings.TOOL_PERMISSIONS.items():
        allowed_roles = {r.strip() for r in roles_str.split(",")}
        if pattern == tool_id or pattern.endswith(":*"):
            prefix = pattern.replace(":*", "")
            if tool_id.startswith(prefix) or pattern == tool_id:
                if user.roles & allowed_roles:
                    return True

    # Fall back to general permission check
    return check_permission(user, "tools:execute")


class PermissionChecker:
    """Dependency for checking permissions."""

    def __init__(self, required_permissions: List[str]):
        self.required_permissions = required_permissions

    async def __call__(self, user: MCPUser = Depends(get_current_user)) -> MCPUser:
        for perm in self.required_permissions:
            if not check_permission(user, perm):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing permission: {perm}",
                )
        return user
