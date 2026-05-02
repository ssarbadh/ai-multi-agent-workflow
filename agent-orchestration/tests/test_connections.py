"""Master test file for backend service connections.

Tests key connections per HLD Data Flow.
Run: pytest tests/test_connections.py -v
"""

import pytest
import asyncio
from app.services.rag_client import RAGClient
from app.services.context_client import ContextManagementClient
from app.services.mcp_client import MCPClient
from app.services.observability_client import ObservabilityClient
from app.core.config import settings


class TestRAGClientConnection:
    def test_rag_client_initialization(self):
        client = RAGClient()
        assert client.base_url == settings.RAG_SERVICE_URL
        assert client.timeout == settings.RAG_SERVICE_TIMEOUT

    def test_rag_client_has_required_methods(self):
        client = RAGClient()
        assert hasattr(client, 'search_knowledge_base')
        assert hasattr(client, 'get_decision_matrix')
        assert hasattr(client, 'search_similar_incidents')
        assert hasattr(client, 'ask_question')
        assert hasattr(client, 'health_check')

    def test_rag_client_methods_are_async(self):
        client = RAGClient()
        assert asyncio.iscoroutinefunction(client.search_knowledge_base)
        assert asyncio.iscoroutinefunction(client.get_decision_matrix)
        assert asyncio.iscoroutinefunction(client.ask_question)


class TestContextClientConnection:
    def test_context_client_initialization(self):
        client = ContextManagementClient()
        assert client.base_url == settings.CONTEXT_MGMT_URL
        assert client.timeout == settings.CONTEXT_MGMT_TIMEOUT

    def test_context_client_has_required_methods(self):
        client = ContextManagementClient()
        assert hasattr(client, 'get_context')
        assert hasattr(client, 'save_state')
        assert hasattr(client, 'save_checkpoint')
        assert hasattr(client, 'get_prompt')

    def test_context_client_methods_are_async(self):
        client = ContextManagementClient()
        assert asyncio.iscoroutinefunction(client.get_context)
        assert asyncio.iscoroutinefunction(client.save_state)
        assert asyncio.iscoroutinefunction(client.save_checkpoint)


class TestMCPClientConnection:
    def test_mcp_client_initialization(self):
        client = MCPClient()
        assert client.base_url == settings.MCP_SERVICE_URL
        assert client.timeout == settings.MCP_SERVICE_TIMEOUT

    def test_mcp_client_has_required_methods(self):
        client = MCPClient()
        assert hasattr(client, 'list_tools')
        assert hasattr(client, 'call_tool')
        assert hasattr(client, 'aws_list_ec2')
        assert hasattr(client, 'rag_search')
        assert hasattr(client, 'health_check')

    def test_mcp_client_methods_are_async(self):
        client = MCPClient()
        assert asyncio.iscoroutinefunction(client.list_tools)
        assert asyncio.iscoroutinefunction(client.call_tool)
        assert asyncio.iscoroutinefunction(client.aws_list_ec2)

    def test_mcp_client_has_aws_extended_methods(self):
        """Test MCP client has extended AWS methods (replacing Azure)."""
        client = MCPClient()
        assert hasattr(client, 'aws_list_eks_clusters')
        assert hasattr(client, 'aws_list_lambda_functions')
        assert hasattr(client, 'aws_list_rds_instances')
        assert hasattr(client, 'aws_send_email')


class TestObservabilityClientConnection:
    def test_observability_client_initialization(self):
        client = ObservabilityClient()
        assert client.base_url == settings.OBSERVABILITY_SERVICE_URL
        assert client.timeout == settings.OBSERVABILITY_SERVICE_TIMEOUT

    def test_observability_client_has_required_methods(self):
        client = ObservabilityClient()
        assert hasattr(client, 'record_agent_run')
        assert hasattr(client, 'record_tool_call')
        assert hasattr(client, 'send_logs')
        assert hasattr(client, 'create_alert')
        assert hasattr(client, 'health_check')

    def test_observability_client_methods_are_async(self):
        client = ObservabilityClient()
        assert asyncio.iscoroutinefunction(client.record_agent_run)
        assert asyncio.iscoroutinefunction(client.send_logs)
        assert asyncio.iscoroutinefunction(client.create_alert)


class TestSharedInfrastructure:
    def test_database_url_configured(self):
        assert settings.DATABASE_URL is not None
        assert "postgresql" in settings.DATABASE_URL

    def test_redis_url_configured(self):
        assert settings.REDIS_URL is not None
        assert "redis" in settings.REDIS_URL.lower()

    def test_service_urls_configured(self):
        assert settings.CONTEXT_MGMT_URL is not None
        assert settings.RAG_SERVICE_URL is not None
        assert settings.MCP_SERVICE_URL is not None
        assert settings.OBSERVABILITY_SERVICE_URL is not None

    def test_service_ports_correct(self):
        assert ":8000" in settings.CONTEXT_MGMT_URL
        assert ":8001" in settings.RAG_SERVICE_URL
        assert ":8005" in settings.MCP_SERVICE_URL
        assert ":8003" in settings.OBSERVABILITY_SERVICE_URL


class TestOrchestratorIntegration:
    def test_orchestrator_imports(self):
        from app.services.orchestrator import OrchestratorService
        orchestrator = OrchestratorService()
        assert orchestrator._rag is not None
        assert orchestrator._context is not None
        assert orchestrator._mcp is not None
        assert orchestrator._observability is not None

    def test_orchestrator_service_clients_initialized(self):
        from app.services.orchestrator import OrchestratorService
        orchestrator = OrchestratorService()
        assert isinstance(orchestrator._rag, RAGClient)
        assert isinstance(orchestrator._context, ContextManagementClient)
        assert isinstance(orchestrator._mcp, MCPClient)
        assert isinstance(orchestrator._observability, ObservabilityClient)


class TestAWSClientIntegration:
    def test_aws_credentials_configured(self):
        assert settings.AWS_ACCESS_KEY_ID is not None
        assert settings.AWS_SECRET_ACCESS_KEY is not None
        assert settings.AWS_REGION is not None

    def test_aws_client_initialization(self):
        from app.clients.aws_client import AWSClient
        client = AWSClient()
        assert client.region == settings.AWS_REGION
        assert client.access_key == settings.AWS_ACCESS_KEY_ID

    def test_aws_client_has_core_methods(self):
        from app.clients.aws_client import AWSClient
        client = AWSClient()
        assert hasattr(client, 'list_ec2_instances')
        assert hasattr(client, 'list_buckets')
        assert hasattr(client, 'send_ssm_command')
        assert hasattr(client, 'describe_vpcs')

    def test_aws_client_has_eks_methods(self):
        from app.clients.aws_client import AWSClient
        client = AWSClient()
        assert hasattr(client, 'list_eks_clusters')
        assert hasattr(client, 'describe_eks_cluster')

    def test_aws_client_has_lambda_methods(self):
        from app.clients.aws_client import AWSClient
        client = AWSClient()
        assert hasattr(client, 'list_lambda_functions')
        assert hasattr(client, 'invoke_lambda')

    def test_aws_client_has_rds_methods(self):
        from app.clients.aws_client import AWSClient
        client = AWSClient()
        assert hasattr(client, 'list_rds_instances')
        assert hasattr(client, 'get_rds_instance')

    def test_aws_client_has_ses_methods(self):
        from app.clients.aws_client import AWSClient
        client = AWSClient()
        assert hasattr(client, 'send_email')
        assert hasattr(client, 'list_verified_emails')

    def test_aws_client_services_initialized(self):
        from app.clients.aws_client import AWSClient
        client = AWSClient()
        assert client.ec2 is not None
        assert client.s3 is not None
        assert client.ssm is not None
        assert client.eks is not None
        assert client.lambda_client is not None
        assert client.rds is not None
        assert client.ses is not None
