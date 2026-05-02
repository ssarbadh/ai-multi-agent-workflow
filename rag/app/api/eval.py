"""API router for evaluation endpoints."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.services.evaluation import evaluation_service
from app.models.schemas import EvalResponse

router = APIRouter(prefix="/eval", tags=["evaluation"])


@router.post("/run", response_model=dict)
async def run_evaluation(
    eval_type: str = "end_to_end",
    session: AsyncSession = Depends(get_db)
):
    """
    Run RAG system evaluation.
    
    Types:
    - retrieval: Evaluate retrieval quality only
    - generation: Evaluate generation quality only
    - end_to_end: Full evaluation
    """
    try:
        if eval_type == "retrieval":
            metrics = await evaluation_service.evaluate_retrieval(session)
            return {"eval_type": "retrieval", "metrics": metrics}
        
        elif eval_type == "generation":
            metrics = await evaluation_service.evaluate_generation(session)
            return {"eval_type": "generation", "metrics": metrics}
        
        elif eval_type == "end_to_end":
            eval_id = await evaluation_service.evaluate_end_to_end(session)
            return {
                "eval_id": eval_id,
                "eval_type": "end_to_end",
                "message": "Evaluation completed successfully"
            }
        
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid eval_type: {eval_type}. Must be 'retrieval', 'generation', or 'end_to_end'"
            )
    
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evaluation failed: {str(e)}"
        )


@router.get("/results", response_model=List[EvalResponse])
async def get_evaluation_results(
    eval_type: Optional[str] = None,
    limit: int = 10,
    session: AsyncSession = Depends(get_db)
):
    """Get historical evaluation results."""
    try:
        results = await evaluation_service.get_evaluation_results(
            session, eval_type, limit
        )
        return results
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get evaluation results: {str(e)}"
        )


@router.get("/status", response_model=dict)
async def get_evaluation_status():
    """Get evaluation system status."""
    dataset = evaluation_service.load_eval_dataset()
    return {
        "enabled": settings.rag_eval_enabled,
        "dataset_path": str(evaluation_service.eval_dataset_path),
        "dataset_size": len(dataset),
        "metrics": settings.rag_eval_metrics,
        "targets": {
            "recall_at_20": settings.rag_target_recall_at_20,
            "faithfulness": settings.rag_target_faithfulness,
            "max_hallucination_rate": settings.rag_max_hallucination_rate,
        }
    }
