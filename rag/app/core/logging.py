"""Enhanced structured logging with correlation IDs and performance tracking."""
import logging
import json
import time
import uuid
from typing import Dict, Any, Optional
from contextvars import ContextVar
from functools import wraps

# Context variables for request tracking
correlation_id_var: ContextVar[str] = ContextVar('correlation_id', default='')
user_id_var: ContextVar[str] = ContextVar('user_id', default='')
session_id_var: ContextVar[str] = ContextVar('session_id', default='')


class StructuredFormatter(logging.Formatter):
    """Custom formatter for structured JSON logging."""
    
    def format(self, record):
        """Format log record as structured JSON."""
        log_entry = {
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add correlation tracking
        correlation_id = correlation_id_var.get('')
        if correlation_id:
            log_entry['correlation_id'] = correlation_id
            
        user_id = user_id_var.get('')
        if user_id:
            log_entry['user_id'] = user_id
            
        session_id = session_id_var.get('')
        if session_id:
            log_entry['session_id'] = session_id
        
        # Add extra fields from record
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)


class RAGLogger:
    """Enhanced logger for RAG system with structured logging and metrics."""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.setup_structured_logging()
    
    def setup_structured_logging(self):
        """Setup structured JSON logging."""
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        
        self.logger.handlers.clear()
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
    
    def log_query_start(self, query: str, query_type: str = "search", **kwargs):
        """Log the start of a RAG query."""
        correlation_id = str(uuid.uuid4())
        correlation_id_var.set(correlation_id)
        
        extra_fields = {
            'event_type': 'query_start',
            'query': query[:100] + '...' if len(query) > 100 else query,  # Truncate long queries
            'query_type': query_type,
            'query_length': len(query),
            **kwargs
        }
        
        self.logger.info("RAG query started", extra={'extra_fields': extra_fields})
        return correlation_id
    
    def log_query_end(self, correlation_id: str, success: bool, duration: float, **kwargs):
        """Log the end of a RAG query."""
        correlation_id_var.set(correlation_id)
        
        extra_fields = {
            'event_type': 'query_end',
            'success': success,
            'duration_ms': round(duration * 1000, 2),
            **kwargs
        }
        
        level = logging.INFO if success else logging.ERROR
        message = "RAG query completed successfully" if success else "RAG query failed"
        
        self.logger.log(level, message, extra={'extra_fields': extra_fields})
    
    def log_pipeline_stage(self, stage: str, duration: float, **kwargs):
        """Log individual pipeline stage performance."""
        extra_fields = {
            'event_type': 'pipeline_stage',
            'stage': stage,
            'duration_ms': round(duration * 1000, 2),
            **kwargs
        }
        
        self.logger.info(f"Pipeline stage '{stage}' completed", extra={'extra_fields': extra_fields})
    
    def log_retrieval_results(self, num_docs: int, top_score: float, avg_score: float, **kwargs):
        """Log document retrieval results."""
        extra_fields = {
            'event_type': 'retrieval_results',
            'num_documents': num_docs,
            'top_score': round(top_score, 4),
            'avg_score': round(avg_score, 4),
            **kwargs
        }
        
        self.logger.info(f"Retrieved {num_docs} documents", extra={'extra_fields': extra_fields})
    
    def log_llm_request(self, model: str, prompt_tokens: int, completion_tokens: int, cost: float = None, **kwargs):
        """Log LLM API request details."""
        extra_fields = {
            'event_type': 'llm_request',
            'model': model,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': prompt_tokens + completion_tokens,
            **kwargs
        }
        
        if cost is not None:
            extra_fields['cost_usd'] = round(cost, 6)
        
        self.logger.info(f"LLM request to {model}", extra={'extra_fields': extra_fields})
    
    def log_evaluation_result(self, eval_type: str, metrics: Dict[str, Any], **kwargs):
        """Log evaluation results."""
        extra_fields = {
            'event_type': 'evaluation_result',
            'eval_type': eval_type,
            'metrics': metrics,
            **kwargs
        }
        
        self.logger.info(f"Evaluation completed: {eval_type}", extra={'extra_fields': extra_fields})
    
    def log_error(self, error: Exception, context: Dict[str, Any] = None, **kwargs):
        """Log errors with full context."""
        extra_fields = {
            'event_type': 'error',
            'error_type': type(error).__name__,
            'error_message': str(error),
            **kwargs
        }
        
        if context:
            extra_fields['context'] = context
        
        self.logger.error(f"Error occurred: {type(error).__name__}", 
                         extra={'extra_fields': extra_fields}, exc_info=True)
    
    def log_user_feedback(self, feedback_type: str, score: int, comment: str = None, **kwargs):
        """Log user feedback."""
        extra_fields = {
            'event_type': 'user_feedback',
            'feedback_type': feedback_type,
            'score': score,
            **kwargs
        }
        
        if comment:
            extra_fields['comment'] = comment[:200]  # Truncate long comments
        
        self.logger.info(f"User feedback received: {feedback_type}", extra={'extra_fields': extra_fields})


def with_correlation_id(func):
    """Decorator to ensure correlation ID is set for function execution."""
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        if not correlation_id_var.get(''):
            correlation_id_var.set(str(uuid.uuid4()))
        return await func(*args, **kwargs)
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        if not correlation_id_var.get(''):
            correlation_id_var.set(str(uuid.uuid4()))
        return func(*args, **kwargs)
    
    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


def log_performance(stage_name: str):
    """Decorator to log performance of function execution."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            logger = RAGLogger(func.__module__)
            
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                logger.log_pipeline_stage(stage_name, duration, success=True)
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.log_pipeline_stage(stage_name, duration, success=False, error=str(e))
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            logger = RAGLogger(func.__module__)
            
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                logger.log_pipeline_stage(stage_name, duration, success=True)
                return result
            except Exception as e:
                duration = time.time() - start_time
                logger.log_pipeline_stage(stage_name, duration, success=False, error=str(e))
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


# Global logger instances
rag_logger = RAGLogger("rag_system")
query_logger = RAGLogger("rag_query")
eval_logger = RAGLogger("rag_evaluation")

# Import asyncio at the end to avoid circular imports
import asyncio