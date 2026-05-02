"""Celery application configuration."""
import logging
from celery import Celery
from app.core.config import settings

logger = logging.getLogger(__name__)

# Create Celery app
celery_app = Celery(
    "rag_workers",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.indexing_tasks", "app.workers.embedding_tasks"]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour
    task_soft_time_limit=3300,  # 55 minutes
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    result_expires=3600,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
)

# Task routes — must match registered task names.
# indexing_tasks.py uses explicit name="indexing.*" so routes like
# "app.workers.indexing_tasks.*" never match; tasks then go to the default "celery"
# queue while workers only listen to --queues=indexing (jobs stuck "pending").
celery_app.conf.task_routes = {
    "indexing.*": {"queue": "indexing"},
    "embedding.*": {"queue": "embedding"},
    "app.workers.indexing_tasks.*": {"queue": "indexing"},
    "app.workers.embedding_tasks.*": {"queue": "embedding"},
}

# Celery Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    "incremental-refresh-every-30-minutes": {
        "task": "indexing.incremental_refresh",
        "schedule": 1800.0,  # 30 minutes in seconds
        "options": {"queue": "indexing"},
    },
}

logger.info("Celery app configured successfully with beat schedule")
