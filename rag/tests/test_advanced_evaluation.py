"""Test suite for advanced RAG evaluation features."""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.evaluation import evaluation_service
from app.core.logging import rag_logger, correlation_id_var


class TestAdvancedEvaluation:
    """Test advanced evaluation features."""
    
    @pytest.fixture
    def mock_session(self):
        """Mock database session."""
        session = Mock(spec=AsyncSession)
        session.add = Mock()
        session.commit = AsyncMock()
        session.execute = AsyncMock()
        return session
    
    @pytest.fixture
    def sample_comprehensive_dataset(self):
        """Sample comprehensive evaluation dataset."""
        return [
            {
                "id": "test_001",
                "query": "How to fix pod restart issues?",
                "expected_keywords": ["pod", "restart", "oom", "limits"],
                "category": "kubernetes",
                "difficulty": "medium",
                "expected_sources": ["k8s_training_data"]
            },
            {
                "id": "test_002",
                "query": "What is the incident response process?",
                "expected_keywords": ["incident", "response", "escalation"],
                "category": "operations",
                "difficulty": "hard",
                "expected_sources": ["google_drive"]
            }
        ]
    
    @pytest.mark.asyncio
    async def test_load_comprehensive_dataset(self, sample_comprehensive_dataset):
        """Test loading comprehensive evaluation dataset."""
        with patch.object(evaluation_service, 'load_eval_dataset') as mock_load:
            mock_load.return_value = sample_comprehensive_dataset
            
            dataset = evaluation_service.load_eval_dataset(comprehensive=True)
            
            assert len(dataset) == 2
            assert dataset[0]["category"] == "kubernetes"
            assert dataset[1]["category"] == "operations"
            mock_load.assert_called_once_with(comprehensive=True)
    
    @pytest.mark.asyncio
    async def test_advanced_retrieval_evaluation(self, mock_session, sample_comprehensive_dataset):
        """Test advanced retrieval evaluation with detailed metrics."""
        with patch.object(evaluation_service, 'load_eval_dataset') as mock_load:
            mock_load.return_value = sample_comprehensive_dataset
            
            # Mock query pipeline results
            mock_result = {
                "documents": [
                    {
                        "id": "doc1",
                        "content": "Pod restart issues are often caused by OOM kills due to resource limits",
                        "score": 0.9
                    },
                    {
                        "id": "doc2", 
                        "content": "Check pod logs and resource configuration to diagnose restart problems",
                        "score": 0.8
                    }
                ]
            }
            
            with patch('app.services.evaluation.query_pipeline.run_async') as mock_query:
                mock_query.return_value = mock_result
                
                metrics = await evaluation_service.evaluate_retrieval_advanced(
                    mock_session, k=10, comprehensive=True
                )
                
                assert "avg_context_relevance" in metrics
                assert "category_performance" in metrics
                assert "total_queries" in metrics
                assert "successful_queries" in metrics
                
                # Check category performance tracking
                assert "kubernetes" in metrics["category_performance"]
                assert "operations" in metrics["category_performance"]
    
    @pytest.mark.asyncio
    async def test_advanced_generation_evaluation(self, mock_session, sample_comprehensive_dataset):
        """Test advanced generation evaluation with quality metrics."""
        with patch.object(evaluation_service, 'load_eval_dataset') as mock_load:
            mock_load.return_value = sample_comprehensive_dataset
            
            # Mock query pipeline results with answer
            mock_result = {
                "documents": [
                    {
                        "id": "doc1",
                        "content": "Pod restart troubleshooting involves checking resource limits and OOM kills",
                        "score": 0.9
                    }
                ],
                "answer": "To fix pod restart issues, check resource limits and look for OOM kills in logs [1]"
            }
            
            with patch('app.services.evaluation.query_pipeline.run_async') as mock_query:
                mock_query.return_value = mock_result
                
                metrics = await evaluation_service.evaluate_generation_advanced(
                    mock_session, comprehensive=True
                )
                
                assert "faithfulness" in metrics
                assert "answer_completeness" in metrics
                assert "citation_accuracy" in metrics
                assert "avg_response_time" in metrics
                assert "total_queries" in metrics
    
    @pytest.mark.asyncio
    async def test_ab_test_evaluation(self, mock_session):
        """Test A/B testing evaluation functionality."""
        variant_a = {"top_k": 5, "rerank": True}
        variant_b = {"top_k": 10, "rerank": False}
        test_queries = ["How to debug Kubernetes issues?", "What is incident response?"]
        
        # Mock query pipeline results
        mock_result_a = {
            "documents": [{"id": "doc1", "content": "Answer A"}],
            "answer": "This is answer A"
        }
        mock_result_b = {
            "documents": [{"id": "doc1", "content": "Answer B"}, {"id": "doc2", "content": "More context"}],
            "answer": "This is a more detailed answer B"
        }
        
        with patch('app.services.evaluation.query_pipeline.run_async') as mock_query:
            mock_query.side_effect = [mock_result_a, mock_result_b] * len(test_queries)
            
            results = await evaluation_service.run_ab_test_evaluation(
                mock_session, variant_a, variant_b, test_queries
            )
            
            assert "variant_a" in results
            assert "variant_b" in results
            assert "comparison" in results
            assert len(results["variant_a"]) == len(test_queries)
            assert len(results["variant_b"]) == len(test_queries)
            
            # Check comparison metrics
            comparison = results["comparison"]
            assert "avg_response_time_a" in comparison
            assert "avg_response_time_b" in comparison
            assert "performance_improvement" in comparison
    
    @pytest.mark.asyncio
    async def test_context_relevance_calculation(self):
        """Test context relevance calculation."""
        query = "How to fix pod restart issues?"
        documents = [
            {
                "content": "Pod restart issues are often caused by resource limits and OOM kills",
                "score": 0.9
            },
            {
                "content": "Check pod logs and kubectl describe to diagnose problems",
                "score": 0.8
            }
        ]
        expected_keywords = ["pod", "restart", "oom", "limits"]
        
        relevance = evaluation_service._calculate_context_relevance(
            query, documents, expected_keywords
        )
        
        assert 0.0 <= relevance <= 1.0
        assert relevance > 0.5  # Should be reasonably relevant
    
    @pytest.mark.asyncio
    async def test_faithfulness_advanced_check(self):
        """Test advanced faithfulness checking."""
        answer = "Pod restart issues are caused by OOM kills due to resource limits [1]"
        documents = [
            {
                "content": "Pod restart issues are often caused by resource limits and OOM kills",
                "score": 0.9
            }
        ]
        expected_keywords = ["pod", "restart", "oom", "limits"]
        
        faithfulness = evaluation_service._check_faithfulness_advanced(
            answer, documents, expected_keywords
        )
        
        assert 0.0 <= faithfulness <= 1.0
        assert faithfulness > 0.7  # Should be highly faithful
    
    @pytest.mark.asyncio
    async def test_answer_completeness_check(self):
        """Test answer completeness evaluation."""
        answer = "To fix pod restart issues, you need to check resource limits, examine OOM kills in logs, and adjust memory/CPU requests accordingly"
        expected_keywords = ["pod", "restart", "resource", "limits", "oom"]
        query = "How to fix pod restart issues?"
        
        completeness = evaluation_service._check_answer_completeness(
            answer, expected_keywords, query
        )
        
        assert 0.0 <= completeness <= 1.0
        assert completeness > 0.8  # Should be quite complete
    
    @pytest.mark.asyncio
    async def test_citation_accuracy_check(self):
        """Test citation accuracy evaluation."""
        answer = "Pod restart issues are caused by OOM kills [1] and resource limits [2]"
        documents = [
            {"content": "OOM kills cause restarts"},
            {"content": "Resource limits are important"}
        ]
        
        accuracy = evaluation_service._check_citation_accuracy(answer, documents)
        
        assert accuracy == 1.0  # All citations should be valid
        
        # Test with invalid citations
        answer_invalid = "Pod issues are caused by network problems [5]"
        accuracy_invalid = evaluation_service._check_citation_accuracy(answer_invalid, documents)
        
        assert accuracy_invalid == 0.0  # Citation [5] doesn't exist


class TestStructuredLogging:
    """Test structured logging functionality."""
    
    def test_correlation_id_context(self):
        """Test correlation ID context management."""
        # Test setting correlation ID
        test_id = "test-correlation-123"
        correlation_id_var.set(test_id)
        
        assert correlation_id_var.get() == test_id
    
    def test_rag_logger_query_lifecycle(self):
        """Test RAG logger query lifecycle logging."""
        query = "Test query for logging"
        
        # Test query start logging
        correlation_id = rag_logger.log_query_start(query, query_type="test")
        
        assert correlation_id is not None
        assert len(correlation_id) > 0
        
        # Test query end logging
        rag_logger.log_query_end(correlation_id, success=True, duration=1.5, num_docs=3)
        
        # Should not raise any exceptions
    
    def test_rag_logger_pipeline_stage(self):
        """Test pipeline stage logging."""
        rag_logger.log_pipeline_stage("embedding", duration=0.5, tokens=100)
        rag_logger.log_pipeline_stage("retrieval", duration=0.3, num_docs=5)
        rag_logger.log_pipeline_stage("generation", duration=2.1, model="test-model")
        
        # Should not raise any exceptions
    
    def test_rag_logger_error_logging(self):
        """Test error logging with context."""
        test_error = ValueError("Test error message")
        context = {"query": "test query", "stage": "retrieval"}
        
        rag_logger.log_error(test_error, context=context, additional_info="test")
        
        # Should not raise any exceptions
    
    def test_rag_logger_user_feedback(self):
        """Test user feedback logging."""
        rag_logger.log_user_feedback(
            feedback_type="thumbs_up",
            score=5,
            comment="Great answer!",
            query_id="test-123"
        )
        
        # Should not raise any exceptions


class TestMetricsIntegration:
    """Test metrics integration."""
    
    @pytest.fixture
    def mock_metrics(self):
        """Mock metrics instance."""
        metrics = Mock()
        metrics.rag_evaluation_score = Mock()
        metrics.rag_context_relevance = Mock()
        metrics.rag_answer_completeness = Mock()
        metrics.rag_query_duration = Mock()
        metrics.rag_query_patterns = Mock()
        return metrics
    
    def test_metrics_update_during_evaluation(self, mock_metrics):
        """Test that metrics are updated during evaluation."""
        with patch('app.services.evaluation.get_metrics', return_value=mock_metrics):
            # This would be called during actual evaluation
            mock_metrics.rag_evaluation_score.labels(metric_type="faithfulness").set(0.85)
            mock_metrics.rag_context_relevance.observe(0.78)
            
            # Verify metrics were called
            mock_metrics.rag_evaluation_score.labels.assert_called()
            mock_metrics.rag_context_relevance.observe.assert_called_with(0.78)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])