"""SSE streaming endpoints for real-time agent output."""

import logging
import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.redis_client import get_redis
from app.models.models import Run
from app.core.observability import get_metrics
from app.api.sessions import get_pending_events

logger = logging.getLogger(__name__)
router = APIRouter()


async def _create_event_generator(run_id: str, redis, metrics):
    """Generate SSE events from Redis pub/sub with event replay and persistence."""
    metrics.sse_connections_active.inc()
    
    try:
        # Subscribe to run-specific channel
        pubsub = redis.pubsub()
        channel = f"run:{run_id}:events"
        await pubsub.subscribe(channel)
        logger.info(f"SSE subscribed to channel: {channel}")
        
        # Send initial connection event
        yield f"event: connected\ndata: {json.dumps({'run_id': run_id})}\n\n"
        
        # Replay persisted events from Redis
        persisted_events_key = f"run:{run_id}:events:history"
        persisted_events = await redis.lrange(persisted_events_key, 0, -1)
        
        if persisted_events:
            logger.info(f"Replaying {len(persisted_events)} persisted events for {run_id}")
            for event_data in persisted_events:
                try:
                    event = json.loads(event_data)
                    event_type = event.get('event', 'message')
                    sse_data = json.dumps(event.get('data', {}))
                    yield f"event: {event_type}\ndata: {sse_data}\n\n"
                    
                    # If we already have complete event, we're done
                    if event_type == 'complete' or event_type == 'error':
                        await pubsub.unsubscribe(channel)
                        await pubsub.close()
                        return
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse persisted event: {event_data}")
        
        # Send heartbeat and listen for new events
        last_heartbeat = datetime.utcnow()
        
        while True:
            try:
                # Check for messages with timeout
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=1.0
                )
                
                if message and message['type'] == 'message':
                    logger.info(f"Received Redis message for {run_id}: {message['data'][:100]}...")
                    event_data = json.loads(message['data'])
                    event_type = event_data.get('event', 'message')
                    
                    # Persist event to Redis for replay
                    await redis.rpush(persisted_events_key, message['data'])
                    await redis.expire(persisted_events_key, 3600)  # 1 hour TTL
                    
                    # Format SSE event
                    sse_data = json.dumps(event_data.get('data', {}))
                    yield f"event: {event_type}\ndata: {sse_data}\n\n"
                    
                    # Record metrics
                    metrics.sse_events_sent.labels(event_type=event_type).inc()
                    
                    # Check if run is complete
                    if event_type == 'complete' or event_type == 'error':
                        break
                
                # Send periodic heartbeat
                now = datetime.utcnow()
                if (now - last_heartbeat).total_seconds() > 15:
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': now.isoformat()})}\n\n"
                    last_heartbeat = now
                    
            except asyncio.TimeoutError:
                # Send heartbeat on timeout
                now = datetime.utcnow()
                if (now - last_heartbeat).total_seconds() > 15:
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': now.isoformat()})}\n\n"
                    last_heartbeat = now
                
            except Exception as e:
                logger.error(f"Error in event stream: {e}")
                error_data = json.dumps({"error": str(e)})
                yield f"event: error\ndata: {error_data}\n\n"
                break
        
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        
    finally:
        metrics.sse_connections_active.dec()


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    last_event_id: str = None,
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    """
    Stream agent run progress via Server-Sent Events (SSE).
    
    Events:
    - token: LLM token output
    - analysis: Analysis/reasoning summary
    - reference: External reference/citation
    - confidentiality: Confidentiality score update
    - node: Node transition
    - tool: Tool call
    - approval: Approval request
    - vm_output: VM command output
    - status: Status change
    - complete: Run completed
    - error: Error occurred
    """
    metrics = get_metrics()
    
    return StreamingResponse(
        _create_event_generator(run_id, redis, metrics),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# Alias endpoint for frontend compatibility
@router.get("/sse/runs/{run_id}")
async def stream_run_sse(
    run_id: str,
    token: str = Query(None, description="Auth token"),
    lastEventId: str = Query(None, description="Last event ID for reconnection"),
    db: AsyncSession = Depends(get_db),
    redis = Depends(get_redis)
):
    """
    SSE endpoint for chat streaming (frontend-compatible URL).
    Same as /runs/{run_id}/stream but with different URL pattern.
    """
    metrics = get_metrics()
    
    return StreamingResponse(
        _create_event_generator(run_id, redis, metrics),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/sse/vm/{execution_id}")
async def stream_vm_output(
    execution_id: str,
    token: str = Query(None, description="Auth token"),
    lastEventId: str = Query(None, description="Last event ID for reconnection"),
    redis = Depends(get_redis)
):
    """
    SSE endpoint for VM console output streaming.
    
    Events:
    - vm_output: stdout/stderr output
    - vm_prompt: Password/approval prompt
    - complete: Execution completed
    - error: Execution error
    """
    metrics = get_metrics()
    
    async def vm_event_generator():
        metrics.sse_connections_active.inc()
        
        try:
            pubsub = redis.pubsub()
            channel = f"vm:{execution_id}:events"
            await pubsub.subscribe(channel)
            
            yield f"event: connected\ndata: {json.dumps({'execution_id': execution_id})}\n\n"
            
            last_heartbeat = datetime.utcnow()
            
            while True:
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=5.0
                    )
                    
                    if message and message['type'] == 'message':
                        event_data = json.loads(message['data'])
                        event_type = event_data.get('event', 'vm_output')
                        
                        sse_data = json.dumps(event_data.get('data', {}))
                        yield f"event: {event_type}\ndata: {sse_data}\n\n"
                        
                        if event_type == 'complete' or event_type == 'error':
                            break
                    
                    now = datetime.utcnow()
                    if (now - last_heartbeat).total_seconds() > 30:
                        yield f"event: heartbeat\ndata: {json.dumps({'timestamp': now.isoformat()})}\n\n"
                        last_heartbeat = now
                        
                except asyncio.TimeoutError:
                    now = datetime.utcnow()
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': now.isoformat()})}\n\n"
                    last_heartbeat = now
                    
                except Exception as e:
                    logger.error(f"Error in VM event stream: {e}")
                    yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                    break
            
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            
        finally:
            metrics.sse_connections_active.dec()
    
    return StreamingResponse(
        vm_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
