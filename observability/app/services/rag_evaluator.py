"""RAG evaluation metrics calculator per HLD requirements."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from statistics import mean
import numpy as np

from app.models.schemas import (
    RAGEvaluationMetrics, RetrievalQualityMetrics,
    GenerationQualityMetrics, RAGPerformanceMetrics
)

logger = logging.getLogger(__name__)


class RAGEvaluator:
    """
    Calculates RAG evaluation metrics per HLD.
    
    Retrieval Quality:
    - Recall@k, Precision@k, MRR, nDCG@k
    - Context Precision/Recall, Coverage Diversity
    
    Generation Quality:
    - Faithfulness, Hallucination Rate, Answer Relevance
    - Citation Correctness, Conciseness
    
    Performance:
    - Retrieval Latency (BM25, vector, hybrid, rerank)
    - End-to-End Latency, Index Freshness
    """
    
    def __init__(self, db_session=None):
        self.db = db_session
    
    async def calculate_metrics(
        self,
        period_hours: int = 24
    ) -> RAGEvaluationMetrics:
        """Calculate all RAG evaluation metrics for the given period."""
        
        retrieval_quality = await self._calculate_retrieval_quality(period_hours)
        generation_quality = await self._calculate_generation_quality(period_hours)
        performance = await self._calculate_performance_metrics(period_hours)
        
        return RAGEvaluationMetrics(
            timestamp=datetime.now(timezone.utc),
            period_hours=period_hours,
            retrieval_quality=retrieval_quality,
            generation_quality=generation_quality,
            performance=performance
        )
    
    async def _calculate_retrieval_quality(
        self,
        period_hours: int
    ) -> RetrievalQualityMetrics:
        """Calculate retrieval quality metrics."""
        
        # Get evaluation data from database
        eval_data = await self._get_retrieval_evaluations(period_hours)
        
        if not eval_data:
            # Return default values
            return RetrievalQualityMetrics(
                recall_at_k={5: 0.0, 10: 0.0, 20: 0.0},
                precision_at_k={5: 0.0, 10: 0.0, 20: 0.0},
                mrr=0.0,
                ndcg_at_k={5: 0.0, 10: 0.0, 20: 0.0},
                context_precision=0.0,
                context_recall=0.0,
                coverage_diversity=0.0
            )
        
        # Calculate Recall@k
        recall_at_k = {}
        precision_at_k = {}
        ndcg_at_k = {}
        
        for k in [5, 10, 20]:
            recalls = [self._calculate_recall(e, k) for e in eval_data]
            precisions = [self._calculate_precision(e, k) for e in eval_data]
            ndcgs = [self._calculate_ndcg(e, k) for e in eval_data]
            
            recall_at_k[k] = mean(recalls) if recalls else 0.0
            precision_at_k[k] = mean(precisions) if precisions else 0.0
            ndcg_at_k[k] = mean(ndcgs) if ndcgs else 0.0
        
        # Calculate MRR
        mrrs = [self._calculate_mrr(e) for e in eval_data]
        mrr = mean(mrrs) if mrrs else 0.0
        
        # Context precision/recall
        context_precisions = [e.get("context_precision", 0) for e in eval_data]
        context_recalls = [e.get("context_recall", 0) for e in eval_data]
        
        # Coverage diversity: average distinct sources in top-k
        diversities = [e.get("sources_count", 0) / max(e.get("chunks_retrieved", 1), 1) for e in eval_data]
        
        return RetrievalQualityMetrics(
            recall_at_k=recall_at_k,
            precision_at_k=precision_at_k,
            mrr=mrr,
            ndcg_at_k=ndcg_at_k,
            context_precision=mean(context_precisions) if context_precisions else 0.0,
            context_recall=mean(context_recalls) if context_recalls else 0.0,
            coverage_diversity=mean(diversities) if diversities else 0.0
        )
    
    async def _calculate_generation_quality(
        self,
        period_hours: int
    ) -> GenerationQualityMetrics:
        """Calculate generation quality metrics."""
        
        eval_data = await self._get_generation_evaluations(period_hours)
        
        if not eval_data:
            return GenerationQualityMetrics(
                faithfulness=0.0,
                hallucination_rate=0.0,
                answer_relevance=0.0,
                citation_correctness=0.0,
                conciseness_score=0.0
            )
        
        faithfulness_scores = [e.get("faithfulness_score", 0) for e in eval_data]
        relevance_scores = [e.get("relevance_score", 0) for e in eval_data]
        
        # Hallucination rate: 1 - faithfulness (simplified)
        hallucination_rates = [1 - f for f in faithfulness_scores]
        
        # Citation correctness: would need manual evaluation or LLM-as-judge
        citation_scores = [e.get("citation_correctness", 0.9) for e in eval_data]
        
        # Conciseness: based on response length vs expected
        conciseness_scores = [e.get("conciseness_score", 0.8) for e in eval_data]
        
        return GenerationQualityMetrics(
            faithfulness=mean(faithfulness_scores) if faithfulness_scores else 0.0,
            hallucination_rate=mean(hallucination_rates) if hallucination_rates else 0.0,
            answer_relevance=mean(relevance_scores) if relevance_scores else 0.0,
            citation_correctness=mean(citation_scores) if citation_scores else 0.0,
            conciseness_score=mean(conciseness_scores) if conciseness_scores else 0.0
        )
    
    async def _calculate_performance_metrics(
        self,
        period_hours: int
    ) -> RAGPerformanceMetrics:
        """Calculate RAG performance metrics."""
        
        query_data = await self._get_query_metrics(period_hours)
        
        if not query_data:
            return RAGPerformanceMetrics(
                retrieval_latency_bm25_ms=0.0,
                retrieval_latency_vector_ms=0.0,
                retrieval_latency_hybrid_ms=0.0,
                retrieval_latency_rerank_ms=0.0,
                end_to_end_latency_ms=0.0,
                index_freshness_minutes=0.0
            )
        
        # Group by retriever type
        bm25_latencies = [q.get("retrieval_latency_ms", 0) for q in query_data if q.get("retriever_type") == "bm25"]
        vector_latencies = [q.get("retrieval_latency_ms", 0) for q in query_data if q.get("retriever_type") == "vector"]
        hybrid_latencies = [q.get("retrieval_latency_ms", 0) for q in query_data if q.get("retriever_type") == "hybrid"]
        rerank_latencies = [q.get("rerank_latency_ms", 0) for q in query_data if q.get("reranker_used")]
        
        total_latencies = [q.get("total_latency_ms", 0) for q in query_data]
        
        # Index freshness: would query from indexing service
        freshness = await self._get_index_freshness()
        
        return RAGPerformanceMetrics(
            retrieval_latency_bm25_ms=mean(bm25_latencies) if bm25_latencies else 0.0,
            retrieval_latency_vector_ms=mean(vector_latencies) if vector_latencies else 0.0,
            retrieval_latency_hybrid_ms=mean(hybrid_latencies) if hybrid_latencies else 0.0,
            retrieval_latency_rerank_ms=mean(rerank_latencies) if rerank_latencies else 0.0,
            end_to_end_latency_ms=mean(total_latencies) if total_latencies else 0.0,
            index_freshness_minutes=freshness
        )
    
    # Helper methods for metric calculations
    def _calculate_recall(self, eval_item: Dict, k: int) -> float:
        """Calculate Recall@k for a single evaluation."""
        relevant = set(eval_item.get("relevant_ids", []))
        retrieved = eval_item.get("retrieved_ids", [])[:k]
        if not relevant:
            return 0.0
        return len(set(retrieved) & relevant) / len(relevant)
    
    def _calculate_precision(self, eval_item: Dict, k: int) -> float:
        """Calculate Precision@k for a single evaluation."""
        relevant = set(eval_item.get("relevant_ids", []))
        retrieved = eval_item.get("retrieved_ids", [])[:k]
        if not retrieved:
            return 0.0
        return len(set(retrieved) & relevant) / len(retrieved)
    
    def _calculate_mrr(self, eval_item: Dict) -> float:
        """Calculate Mean Reciprocal Rank for a single evaluation."""
        relevant = set(eval_item.get("relevant_ids", []))
        retrieved = eval_item.get("retrieved_ids", [])
        for i, doc_id in enumerate(retrieved):
            if doc_id in relevant:
                return 1.0 / (i + 1)
        return 0.0
    
    def _calculate_ndcg(self, eval_item: Dict, k: int) -> float:
        """Calculate nDCG@k for a single evaluation."""
        relevant = set(eval_item.get("relevant_ids", []))
        retrieved = eval_item.get("retrieved_ids", [])[:k]
        
        if not relevant or not retrieved:
            return 0.0
        
        # DCG
        dcg = 0.0
        for i, doc_id in enumerate(retrieved):
            if doc_id in relevant:
                dcg += 1.0 / np.log2(i + 2)
        
        # Ideal DCG
        ideal_dcg = sum(1.0 / np.log2(i + 2) for i in range(min(len(relevant), k)))
        
        return dcg / ideal_dcg if ideal_dcg > 0 else 0.0
    
    # Data access methods
    async def _get_retrieval_evaluations(self, period_hours: int) -> List[Dict]:
        """Get retrieval evaluation data."""
        # Would query rag_query_metrics with evaluation scores
        return []
    
    async def _get_generation_evaluations(self, period_hours: int) -> List[Dict]:
        """Get generation evaluation data."""
        # Would query evaluation results
        return []
    
    async def _get_query_metrics(self, period_hours: int) -> List[Dict]:
        """Get RAG query metrics."""
        # Would query rag_query_metrics table
        return []
    
    async def _get_index_freshness(self) -> float:
        """Get index freshness in minutes."""
        # Would query RAG service for last index update time
        return 0.0


# Global instance
rag_evaluator = RAGEvaluator()
