"""Evaluation service for RAG system using Haystack."""
import logging
import uuid
from typing import List, Dict, Any
from datetime import datetime
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import EvaluationResult
from app.services.haystack_query import query_pipeline
from app.core.config import settings

logger = logging.getLogger(__name__)


class EvaluationService:
    """Service for evaluating RAG system performance."""
    
    def __init__(self):
        self.eval_dataset_path = Path(settings.rag_eval_dataset_path)
        
    def load_eval_dataset(self) -> List[Dict[str, Any]]:
        """Load evaluation dataset."""
        try:
            if not self.eval_dataset_path.exists():
                logger.warning(f"Eval dataset not found: {self.eval_dataset_path}")
                return []
            
            with open(self.eval_dataset_path, 'r') as f:
                dataset = json.load(f)
            
            logger.info(f"Loaded {len(dataset)} evaluation queries")
            return dataset
        except Exception as e:
            logger.error(f"Failed to load eval dataset: {e}")
            return []
    
    async def evaluate_retrieval(
        self,
        session: AsyncSession,
        k: int = 20
    ) -> Dict[str, float]:
        """
        Evaluate retrieval quality.
        
        Metrics:
        - Recall@k
        - Precision@k
        - MRR (Mean Reciprocal Rank)
        - nDCG@k
        """
        dataset = self.load_eval_dataset()
        
        if not dataset:
            return {}
        
        recall_scores = []
        precision_scores = []
        mrr_scores = []
        
        for item in dataset:
            query = item["query"]
            relevant_docs = item.get("relevant_docs", [])
            
            if not relevant_docs:
                continue
            
            try:
                # Retrieve documents using Haystack
                result = await query_pipeline.run_async(
                    query=query,
                    top_k=k
                )
                
                retrieved_ids = [doc["id"] for doc in result.get("documents", [])]
                
                # Calculate recall
                relevant_retrieved = len(set(retrieved_ids) & set(relevant_docs))
                recall = relevant_retrieved / len(relevant_docs) if relevant_docs else 0
                recall_scores.append(recall)
                
                # Calculate precision
                precision = relevant_retrieved / len(retrieved_ids) if retrieved_ids else 0
                precision_scores.append(precision)
                
                # Calculate MRR
                first_relevant_rank = None
                for i, doc_id in enumerate(retrieved_ids, 1):
                    if doc_id in relevant_docs:
                        first_relevant_rank = i
                        break
                
                mrr = 1.0 / first_relevant_rank if first_relevant_rank else 0.0
                mrr_scores.append(mrr)
                
            except Exception as e:
                logger.error(f"Eval failed for query '{query}': {e}")
                continue
        
        # Aggregate metrics
        metrics = {
            "recall_at_k": sum(recall_scores) / len(recall_scores) if recall_scores else 0.0,
            "precision_at_k": sum(precision_scores) / len(precision_scores) if precision_scores else 0.0,
            "mrr": sum(mrr_scores) / len(mrr_scores) if mrr_scores else 0.0,
        }
        
        logger.info(f"Retrieval evaluation: {metrics}")
        return metrics
    
    async def evaluate_generation(
        self,
        session: AsyncSession
    ) -> Dict[str, float]:
        """
        Evaluate generation quality.
        
        Metrics:
        - Faithfulness
        - Hallucination rate
        - Answer relevance
        """
        dataset = self.load_eval_dataset()
        
        if not dataset:
            return {}
        
        faithfulness_scores = []
        
        for item in dataset:
            query = item["query"]
            expected_keywords = item.get("expected_keywords", [])
            
            try:
                # Use Haystack query pipeline (retrieval + generation)
                result = await query_pipeline.run_async(
                    query=query,
                    top_k=settings.rag_rerank_top_k
                )
                
                if not result.get("documents"):
                    continue
                
                answer = result["answer"]
                documents = result["documents"]
                
                # Simple faithfulness check: verify answer keywords are in context
                faithfulness = self._check_faithfulness(answer, documents, expected_keywords)
                faithfulness_scores.append(faithfulness)
                
            except Exception as e:
                logger.error(f"Generation eval failed for query '{query}': {e}")
                continue
        
        # Aggregate metrics
        avg_faithfulness = sum(faithfulness_scores) / len(faithfulness_scores) if faithfulness_scores else 0.0
        
        metrics = {
            "faithfulness": avg_faithfulness,
            "hallucination_rate": 1.0 - avg_faithfulness,  # Inverse of faithfulness
        }
        
        logger.info(f"Generation evaluation: {metrics}")
        return metrics
    
    def _check_faithfulness(
        self,
        answer: str,
        documents: List[Dict[str, Any]],
        expected_keywords: List[str]
    ) -> float:
        """Check if answer is faithful to retrieved documents."""
        if not expected_keywords:
            return 1.0
        
        # Combine all document content
        context = " ".join([doc.get("content", "") for doc in documents])
        
        # Check if expected keywords are present in answer and context
        keywords_in_answer = sum(1 for kw in expected_keywords if kw.lower() in answer.lower())
        keywords_in_context = sum(1 for kw in expected_keywords if kw.lower() in context.lower())
        
        if keywords_in_context == 0:
            return 0.0
        
        # Faithfulness score: how many answer keywords are grounded in context
        faithfulness = keywords_in_answer / len(expected_keywords)
        return faithfulness
    
    async def evaluate_end_to_end(
        self,
        session: AsyncSession
    ) -> str:
        """
        Run full end-to-end evaluation.
        
        Returns evaluation result ID.
        """
        try:
            # Run retrieval evaluation
            retrieval_metrics = await self.evaluate_retrieval(session)
            
            # Run generation evaluation
            generation_metrics = await self.evaluate_generation(session)
            
            # Combine metrics
            all_metrics = {**retrieval_metrics, **generation_metrics}
            
            # Store result
            eval_id = str(uuid.uuid4())
            eval_result = EvaluationResult(
                id=eval_id,
                eval_type="end_to_end",
                recall_at_k=all_metrics.get("recall_at_k"),
                precision_at_k=all_metrics.get("precision_at_k"),
                mrr=all_metrics.get("mrr"),
                faithfulness=all_metrics.get("faithfulness"),
                hallucination_rate=all_metrics.get("hallucination_rate"),
                metrics=all_metrics,
                dataset_name="default",
                num_queries=len(self.load_eval_dataset()),
            )
            
            session.add(eval_result)
            await session.commit()
            
            logger.info(f"End-to-end evaluation completed: {eval_id}")
            return eval_id
            
        except Exception as e:
            logger.error(f"End-to-end evaluation failed: {e}")
            raise
    
    async def get_evaluation_results(
        self,
        session: AsyncSession,
        eval_type: str = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get historical evaluation results."""
        try:
            stmt = select(EvaluationResult)
            
            if eval_type:
                stmt = stmt.where(EvaluationResult.eval_type == eval_type)
            
            stmt = stmt.order_by(EvaluationResult.created_at.desc()).limit(limit)
            
            result = await session.execute(stmt)
            evals = result.scalars().all()
            
            return [
                {
                    "id": e.id,
                    "eval_type": e.eval_type,
                    "recall_at_k": e.recall_at_k,
                    "precision_at_k": e.precision_at_k,
                    "mrr": e.mrr,
                    "faithfulness": e.faithfulness,
                    "hallucination_rate": e.hallucination_rate,
                    "metrics": e.metrics,
                    "dataset_name": e.dataset_name,
                    "num_queries": e.num_queries,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in evals
            ]
        except Exception as e:
            logger.error(f"Failed to get evaluation results: {e}")
            return []


# Global evaluation service instance
evaluation_service = EvaluationService()
