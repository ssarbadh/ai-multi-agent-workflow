"""
Master test file for MCP service.
Tests all core functionality without requiring external dependencies.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# ============== Config Tests ==============

class TestConfig:
    """Test configuration settings."""

    def test_settings_defaults(self):
        """Test default settings values."""
        from app.core.config import Settings

        settings = Settings(
            DATABASE_URL="postgresql://test",
            REDIS_URL="redis://test",
        )
        assert settings.SERVICE_NAME == "aegisops-mcp"
        assert settings.API_PORT == 8005
        assert settings.MCP_TRANSPORT == "sse"

    def test_cors_origins_parsing(self):
        """Test CORS origins parsing from JSON string."""
        from app.core.config import Settings

        settings = Settings(
            DATABASE_URL="postgresql://test",
            REDIS_URL="redis://test",
            CORS_ORIGINS='["http://localhost:3000","http://localhost:8000"]',
        )
        assert len(settings.CORS_ORIGINS) == 2
        assert "http://localhost:3000" in settings.CORS_ORIGINS

    def test_api_keys_parsing(self):
        """Test API keys parsing from JSON string."""
        from app.core.config import Settings

        settings = Settings(
            DATABASE_URL="postgresql://test",
            REDIS_URL="redis://test",
            API_KEYS='["key1","key2"]',
        )
        assert len(settings.API_KEYS) == 2
        assert "key1" in settings.API_KEYS


# ============== Security Tests ==============

class TestSecurity:
    """Test security utilities."""

    def test_hash_api_key(self):
        """Test API key hashing."""
        from app.core.security import hash_api_key

        key = "test-api-key"
        hashed = hash_api_key(key)
        assert len(hashed) == 64  # SHA256 hex digest
        assert hash_api_key(key) == hashed  # Consistent

    def test_generate_api_key(self):
        """Test API key generation."""
        from app.core.security import generate_api_key

        key = generate_api_key()
        assert key.startswith("mcp-")
        assert len(key) > 40

    def test_verify_api_key_valid(self):
        """Test valid API key verification."""
        from app.core.security import verify_api_key

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.API_KEYS = ["valid-key"]
            assert verify_api_key("valid-key") is True
            assert verify_api_key("invalid-key") is False

    def test_verify_api_key_no_keys_configured(self):
        """Test API key verification when no keys configured."""
        from app.core.security import verify_api_key

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.API_KEYS = []
            assert verify_api_key("any-key") is True

    def test_create_access_token(self):
        """Test JWT token creation."""
        from app.core.security import create_access_token, decode_token

        with patch("app.core.security.settings") as mock_settings:
            mock_settings.SECRET_KEY = "test-secret"
            mock_settings.JWT_ALGORITHM = "HS256"
            mock_settings.JWT_EXPIRY_MINUTES = 60

            token = create_access_token(
                subject="user123",
                tenant_id="tenant1",
                roles=["admin"],
            )
            assert token is not None

            payload = decode_token(token)
            assert payload.sub == "user123"
            assert payload.tenant_id == "tenant1"
            assert "admin" in payload.roles

    def test_get_permissions_for_roles(self):
        """Test permission extraction from roles."""
        from app.core.security import get_permissions_for_roles

        admin_perms = get_permissions_for_roles(["admin"])
        assert "tools:*" in admin_perms
        assert "sessions:*" in admin_perms

        viewer_perms = get_permissions_for_roles(["viewer"])
        assert "tools:list" in viewer_perms
        assert "tools:*" not in viewer_perms

    def test_check_permission(self):
        """Test permission checking."""
        from app.core.security import check_permission, MCPUser

        admin = MCPUser(
            id="admin1",
            roles={"admin"},
            permissions={"tools:*", "sessions:*"},
        )
        assert check_permission(admin, "tools:execute") is True
        assert check_permission(admin, "sessions:create") is True

        viewer = MCPUser(
            id="viewer1",
            roles={"viewer"},
            permissions={"tools:list", "resources:read"},
        )
        assert check_permission(viewer, "tools:list") is True
        assert check_permission(viewer, "tools:execute") is False


# ============== Schema Tests ==============

class TestSchemas:
    """Test Pydantic schemas."""

    def test_tool_definition(self):
        """Test ToolDefinition schema."""
        from app.models.schemas import ToolDefinition, ToolInputSchema

        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            inputSchema=ToolInputSchema(
                type="object",
                properties={"param1": {"type": "string"}},
                required=["param1"],
            ),
        )
        assert tool.name == "test_tool"
        assert tool.inputSchema.type == "object"
        assert "param1" in tool.inputSchema.properties

    def test_tool_call_request(self):
        """Test ToolCallRequest schema."""
        from app.models.schemas import ToolCallRequest

        request = ToolCallRequest(
            name="test_tool",
            arguments={"param1": "value1"},
        )
        assert request.name == "test_tool"
        assert request.arguments["param1"] == "value1"

    def test_tool_call_response(self):
        """Test ToolCallResponse schema."""
        from app.models.schemas import ToolCallResponse

        response = ToolCallResponse(
            content=[{"type": "text", "text": "Result"}],
            isError=False,
        )
        assert len(response.content) == 1
        assert response.isError is False

    def test_session_schema(self):
        """Test Session schema."""
        from app.models.schemas import Session

        session = Session(
            session_id="sess-123",
            server_id="server-1",
            client_id="client-1",
            status="active",
        )
        assert session.session_id == "sess-123"
        assert session.status == "active"

    def test_server_registration(self):
        """Test ServerRegistration schema."""
        from app.models.schemas import ServerRegistration, MCPTransport

        reg = ServerRegistration(
            server_id="server-1",
            name="Test Server",
            transport=MCPTransport.SSE,
        )
        assert reg.server_id == "server-1"
        assert reg.transport == MCPTransport.SSE

    def test_health_status(self):
        """Test HealthStatus schema."""
        from app.models.schemas import HealthStatus

        health = HealthStatus(
            status="healthy",
            service="mcp",
            version="0.1.0",
        )
        assert health.status == "healthy"


# ============== Base Server Tests ==============

class TestBaseMCPServer:
    """Test base MCP server functionality."""

    @pytest.mark.asyncio
    async def test_register_tool(self):
        """Test tool registration."""
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")

        async def handler(param1: str):
            return f"Result: {param1}"

        server.register_tool(
            name="test_tool",
            description="Test tool",
            handler=handler,
            input_schema={"type": "object", "properties": {"param1": {"type": "string"}}},
        )

        tools = server.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "test_tool"

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        """Test successful tool call."""
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")

        async def handler(param1: str):
            return f"Result: {param1}"

        server.register_tool(
            name="test_tool",
            description="Test tool",
            handler=handler,
        )

        response = await server.call_tool("test_tool", {"param1": "hello"})
        assert response.isError is False
        assert "Result: hello" in response.content[0]["text"]

    @pytest.mark.asyncio
    async def test_call_tool_not_found(self):
        """Test tool call for non-existent tool."""
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")
        response = await server.call_tool("nonexistent", {})
        assert response.isError is True
        assert "not found" in response.content[0]["text"].lower()

    @pytest.mark.asyncio
    async def test_register_resource(self):
        """Test resource registration."""
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")

        async def handler():
            return "Resource content"

        server.register_resource(
            uri="test://resource",
            name="Test Resource",
            handler=handler,
            description="A test resource",
        )

        resources = server.list_resources()
        assert len(resources) == 1
        assert resources[0].uri == "test://resource"

    @pytest.mark.asyncio
    async def test_read_resource(self):
        """Test resource reading."""
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")

        async def handler():
            return "Resource content"

        server.register_resource(
            uri="test://resource",
            name="Test Resource",
            handler=handler,
        )

        response = await server.read_resource("test://resource")
        assert "Resource content" in response.contents[0]["text"]

    @pytest.mark.asyncio
    async def test_register_prompt(self):
        """Test prompt registration."""
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")

        async def handler(context: str):
            return [{"role": "user", "content": {"type": "text", "text": context}}]

        server.register_prompt(
            name="test_prompt",
            handler=handler,
            description="A test prompt",
            arguments=[{"name": "context", "required": True}],
        )

        prompts = server.list_prompts()
        assert len(prompts) == 1
        assert prompts[0].name == "test_prompt"

    def test_get_server_info(self):
        """Test server info retrieval."""
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server", version="1.0.0")
        info = server.get_server_info()

        assert info.name == "test-server"
        assert info.version == "1.0.0"
        assert info.protocol_version == "2024-11-05"


# ============== Session Manager Tests ==============

class TestSessionManager:
    """Test session management."""

    @pytest.mark.asyncio
    async def test_create_session(self):
        """Test session creation."""
        from app.services.session_manager import SessionManager

        manager = SessionManager()

        with patch("app.services.session_manager.redis_client") as mock_redis:
            mock_redis.set_json = AsyncMock(return_value=True)

            session = await manager.create_session(
                server_id="server-1",
                client_id="client-1",
                tenant_id="tenant-1",
            )

            assert session.server_id == "server-1"
            assert session.client_id == "client-1"
            assert session.status == "active"

    @pytest.mark.asyncio
    async def test_get_session(self):
        """Test session retrieval."""
        from app.services.session_manager import SessionManager

        manager = SessionManager()

        with patch("app.services.session_manager.redis_client") as mock_redis:
            mock_redis.set_json = AsyncMock(return_value=True)
            mock_redis.get_json = AsyncMock(return_value=None)

            session = await manager.create_session(
                server_id="server-1",
                client_id="client-1",
            )

            retrieved = await manager.get_session(session.session_id)
            assert retrieved is not None
            assert retrieved.session_id == session.session_id

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test session closing."""
        from app.services.session_manager import SessionManager

        manager = SessionManager()

        with patch("app.services.session_manager.redis_client") as mock_redis:
            mock_redis.set_json = AsyncMock(return_value=True)
            mock_redis.get_json = AsyncMock(return_value=None)

            session = await manager.create_session(
                server_id="server-1",
                client_id="client-1",
            )

            success = await manager.close_session(session.session_id)
            assert success is True

            retrieved = await manager.get_session(session.session_id)
            assert retrieved.status == "closed"

    @pytest.mark.asyncio
    async def test_list_sessions(self):
        """Test session listing."""
        from app.services.session_manager import SessionManager

        manager = SessionManager()

        with patch("app.services.session_manager.redis_client") as mock_redis:
            mock_redis.set_json = AsyncMock(return_value=True)

            await manager.create_session(server_id="server-1")
            await manager.create_session(server_id="server-1")
            await manager.create_session(server_id="server-2")

            all_sessions = await manager.list_sessions()
            assert all_sessions.total == 3

            server1_sessions = await manager.list_sessions(server_id="server-1")
            assert server1_sessions.total == 2


# ============== OpenAPI Bridge Tests ==============

class TestOpenAPIBridge:
    """Test OpenAPI to MCP conversion."""

    def test_convert_simple_operation(self):
        """Test converting a simple OpenAPI operation."""
        from app.services.openapi_bridge import OpenAPIBridge

        bridge = OpenAPIBridge()

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "get": {
                        "operationId": "listUsers",
                        "summary": "List all users",
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
                                "schema": {"type": "integer"},
                            }
                        ],
                    }
                }
            },
        }

        result = bridge.convert_to_tools(spec, "test-server")
        assert result.tools_created == 1
        assert result.tools[0].name == "api_listUsers"
        assert "limit" in result.tools[0].inputSchema.properties

    def test_convert_with_request_body(self):
        """Test converting operation with request body."""
        from app.services.openapi_bridge import OpenAPIBridge

        bridge = OpenAPIBridge()

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/users": {
                    "post": {
                        "operationId": "createUser",
                        "summary": "Create a user",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                        "required": ["name", "email"],
                                    }
                                }
                            }
                        },
                    }
                }
            },
        }

        result = bridge.convert_to_tools(spec, "test-server")
        assert result.tools_created == 1
        assert "name" in result.tools[0].inputSchema.properties
        assert "email" in result.tools[0].inputSchema.properties
        assert "name" in result.tools[0].inputSchema.required

    def test_convert_with_path_filters(self):
        """Test converting with path filters."""
        from app.services.openapi_bridge import OpenAPIBridge

        bridge = OpenAPIBridge()

        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/users": {"get": {"operationId": "listUsers"}},
                "/admin/users": {"get": {"operationId": "adminListUsers"}},
                "/public/info": {"get": {"operationId": "publicInfo"}},
            },
        }

        # Include only /users
        result = bridge.convert_to_tools(
            spec, "test-server", include_paths=["/users"]
        )
        assert result.tools_created == 1
        assert result.tools[0].name == "api_listUsers"

        # Exclude /admin
        result = bridge.convert_to_tools(
            spec, "test-server", exclude_paths=["/admin"]
        )
        assert result.tools_created == 2


# ============== Gateway Tests ==============

class TestGateway:
    """Test MCP gateway functionality."""

    @pytest.mark.asyncio
    async def test_route_tool_call_permission_denied(self):
        """Test tool call routing with permission denied."""
        from app.services.gateway import MCPGateway
        from app.core.security import MCPUser
        from app.models.schemas import ToolCallRequest

        gateway = MCPGateway()

        user = MCPUser(
            id="viewer1",
            roles={"viewer"},
            permissions={"tools:list"},  # No execute permission
        )

        request = ToolCallRequest(name="admin_tool", arguments={})

        with patch("app.services.gateway.check_tool_permission", return_value=False):
            response = await gateway.route_tool_call(request, user=user)
            assert response.isError is True
            assert "Permission denied" in response.content[0]["text"]


# ============== Integration Tests ==============

class TestIntegration:
    """Integration tests for MCP service."""

    @pytest.mark.asyncio
    async def test_server_registry_initialization(self):
        """Test server registry initialization."""
        from app.services.server_registry import ServerRegistry

        registry = ServerRegistry()

        with patch("app.services.server_registry.redis_client") as mock_redis:
            mock_redis.set_json = AsyncMock(return_value=True)

            # Mock HTTP client for servers
            mock_http = AsyncMock()
            mock_http.aclose = AsyncMock()

            with patch("httpx.AsyncClient", return_value=mock_http):
                await registry.initialize()

                servers = registry.list_servers()
                assert len(servers) >= 3  # infra, rag, context servers

                tools = registry.list_all_tools()
                assert len(tools) > 0

                await registry.shutdown()

    @pytest.mark.asyncio
    async def test_find_tool(self):
        """Test finding a tool across servers."""
        from app.services.server_registry import ServerRegistry

        registry = ServerRegistry()

        with patch("app.services.server_registry.redis_client") as mock_redis:
            mock_redis.set_json = AsyncMock(return_value=True)

            mock_http = AsyncMock()
            mock_http.aclose = AsyncMock()

            with patch("httpx.AsyncClient", return_value=mock_http):
                await registry.initialize()

                # Find a known tool
                result = registry.find_tool("rag_search")
                assert result is not None
                server_id, server = result
                assert server_id == "rag-server"

                # Non-existent tool
                result = registry.find_tool("nonexistent_tool")
                assert result is None

                await registry.shutdown()


# ============== Edge Cases ==============

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_tool_arguments(self):
        """Test tool call with empty arguments."""
        from app.models.schemas import ToolCallRequest

        request = ToolCallRequest(name="test_tool")
        assert request.arguments == {}

    def test_session_with_no_metadata(self):
        """Test session creation without metadata."""
        from app.models.schemas import Session

        session = Session(
            session_id="sess-1",
            server_id="server-1",
        )
        assert session.metadata == {}

    @pytest.mark.asyncio
    async def test_tool_handler_exception(self):
        """Test tool call when handler raises exception."""
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")

        async def failing_handler():
            raise ValueError("Handler error")

        server.register_tool(
            name="failing_tool",
            description="A failing tool",
            handler=failing_handler,
        )

        response = await server.call_tool("failing_tool", {})
        assert response.isError is True
        assert "Error" in response.content[0]["text"]

    def test_mcp_user_with_empty_permissions(self):
        """Test MCPUser with no permissions."""
        from app.core.security import MCPUser, check_permission

        user = MCPUser(
            id="empty-user",
            roles=set(),
            permissions=set(),
        )
        assert check_permission(user, "any:permission") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ============== Stdio Transport Tests ==============

class TestStdioTransport:
    """Test stdio transport for MCP servers."""

    @pytest.mark.asyncio
    async def test_handle_initialize(self):
        """Test initialize message handling."""
        from app.cli import StdioTransport
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")
        transport = StdioTransport(server)

        message = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        response = await transport.handle_message(message)

        assert response["id"] == 1
        assert "result" in response
        assert response["result"]["protocolVersion"] == "2024-11-05"
        assert "capabilities" in response["result"]

    @pytest.mark.asyncio
    async def test_handle_tools_list(self):
        """Test tools/list message handling."""
        from app.cli import StdioTransport
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")
        server.register_tool(
            name="test_tool",
            description="Test",
            handler=lambda: "result",
        )
        transport = StdioTransport(server)

        message = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        response = await transport.handle_message(message)

        assert response["id"] == 2
        assert "result" in response
        assert len(response["result"]["tools"]) == 1

    @pytest.mark.asyncio
    async def test_handle_tools_call(self):
        """Test tools/call message handling."""
        from app.cli import StdioTransport
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")

        async def handler(value: str):
            return f"Got: {value}"

        server.register_tool(
            name="echo",
            description="Echo tool",
            handler=handler,
        )
        transport = StdioTransport(server)

        message = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"value": "hello"}},
        }
        response = await transport.handle_message(message)

        assert response["id"] == 3
        assert "result" in response
        assert response["result"]["isError"] is False

    @pytest.mark.asyncio
    async def test_handle_unknown_method(self):
        """Test unknown method handling."""
        from app.cli import StdioTransport
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")
        transport = StdioTransport(server)

        message = {"jsonrpc": "2.0", "id": 4, "method": "unknown/method", "params": {}}
        response = await transport.handle_message(message)

        assert response["id"] == 4
        assert "error" in response
        assert response["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_handle_ping(self):
        """Test ping message handling."""
        from app.cli import StdioTransport
        from app.servers.base import BaseMCPServer

        class TestServer(BaseMCPServer):
            async def initialize(self):
                pass

        server = TestServer("test-server")
        transport = StdioTransport(server)

        message = {"jsonrpc": "2.0", "id": 5, "method": "ping", "params": {}}
        response = await transport.handle_message(message)

        assert response["id"] == 5
        assert response["result"] == {}
