"""API endpoints for Incident Analysis.

Provides endpoints for event correlation, anomaly detection,
and comprehensive incident analysis.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.agents.incident_analysis_agent import incident_analysis_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incident-analysis", tags=["Incident Analysis"])


# ===================================
# Request/Response Models
# ===================================

class EventInput(BaseModel):
    """Input event for analysis."""
    id: Optional[str] = None
    timestamp: str = Field(..., description="ISO format timestamp")
    source: str = Field(..., description="Event source (prometheus, logs, etc.)")
    severity: str = Field(..., description="Severity level (critical, warning, info)")
    message: str = Field(..., description="Event message")
    labels: Dict[str, str] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MetricInput(BaseModel):
    """Input metric for anomaly detection."""
    name: str = Field(..., description="Metric name")
    timestamp: str = Field(..., description="ISO format timestamp")
    value: float = Field(..., description="Metric value")
    labels: Dict[str, str] = Field(default_factory=dict)


class IncidentAnalysisRequest(BaseModel):
    """Request for incident analysis."""
    events: List[EventInput] = Field(..., description="List of events to analyze")
    metrics: Optional[List[MetricInput]] = Field(None, description="Optional metrics for anomaly detection")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")


class IncidentAnalysisResponse(BaseModel):
    """Response from incident analysis."""
    incident: Dict[str, Any]
    anomalies: List[Dict[str, Any]]
    root_cause: str
    impact_assessment: str
    remediation_steps: List[str]
    similar_incidents: List[str]
    confidence_score: float
    analysis_timestamp: str


# ===================================
# API Endpoints
# ===================================

@router.post("/analyze", response_model=IncidentAnalysisResponse)
async def analyze_incident(request: IncidentAnalysisRequest):
    """
    Perform comprehensive incident analysis.
    
    This endpoint:
    1. Correlates events to identify incident patterns
    2. Detects anomalies in provided metrics
    3. Performs root cause analysis using LLM
    4. Generates remediation recommendations
    5. Finds similar historical incidents
    
    Example:
    ```json
    {
      "events": [
        {
          "timestamp": "2024-02-03T10:00:00Z",
          "source": "prometheus",
          "severity": "critical",
          "message": "High CPU usage detected",
          "labels": {"service": "api-gateway"}
        }
      ],
      "metrics": [
        {
          "name": "cpu_usage",
          "timestamp": "2024-02-03T10:00:00Z",
          "value": 95.5,
          "labels": {"service": "api-gateway"}
        }
      ]
    }
    ```
    """
    try:
        logger.info(f"Received incident analysis request with {len(request.events)} events")
        
        # Convert Pydantic models to dicts
        events = [event.dict() for event in request.events]
        metrics = [metric.dict() for metric in request.metrics] if request.metrics else None
        
        # Perform analysis
        analysis = await incident_analysis_agent.analyze_incident(
            events=events,
            metrics=metrics,
            context=request.context
        )
        
        if not analysis:
            raise HTTPException(
                status_code=404,
                detail="No incidents found in provided events"
            )
        
        # Convert to response format
        response_dict = incident_analysis_agent.to_dict(analysis)
        
        return IncidentAnalysisResponse(**response_dict)
        
    except Exception as e:
        logger.error(f"Incident analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/correlate-events")
async def correlate_events(events: List[EventInput]):
    """
    Correlate events to identify incident patterns.
    
    Returns groups of correlated events that likely belong to the same incident.
    """
    try:
        from app.services.event_correlator import event_correlator
        
        # Convert to Event objects
        event_dicts = [event.dict() for event in events]
        event_objects = incident_analysis_agent._convert_to_events(event_dicts)
        
        # Correlate
        incidents = await event_correlator.correlate_events(event_objects)
        
        # Convert to response
        result = []
        for incident in incidents:
            result.append({
                'incident_id': incident.id,
                'severity': incident.severity,
                'affected_services': list(incident.affected_services),
                'event_count': len(incident.events),
                'correlation_score': incident.correlation_score,
                'summary': incident.summary,
                'start_time': incident.start_time.isoformat(),
                'end_time': incident.end_time.isoformat() if incident.end_time else None,
                'events': [
                    {
                        'id': e.id,
                        'timestamp': e.timestamp.isoformat(),
                        'source': e.source,
                        'severity': e.severity,
                        'message': e.message
                    }
                    for e in incident.events
                ]
            })
        
        return {
            'incidents': result,
            'total_events': len(events),
            'total_incidents': len(incidents)
        }
        
    except Exception as e:
        logger.error(f"Event correlation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/detect-anomalies")
async def detect_anomalies(
    metrics: List[MetricInput],
    method: str = Query('all', description="Detection method: statistical, threshold, rate_of_change, all")
):
    """
    Detect anomalies in metric data.
    
    Supports multiple detection methods:
    - statistical: Z-score based detection
    - threshold: Predefined threshold violations
    - rate_of_change: Sudden spikes or drops
    - all: Combine all methods
    """
    try:
        from app.services.anomaly_detector import anomaly_detector
        
        # Group metrics by name
        metric_dicts = [metric.dict() for metric in metrics]
        metrics_by_name = incident_analysis_agent._convert_to_metrics(metric_dicts)
        
        # Detect anomalies
        all_anomalies = []
        for metric_name, data_points in metrics_by_name.items():
            anomalies = await anomaly_detector.detect_anomalies(
                metric_name,
                data_points,
                method=method
            )
            all_anomalies.extend(anomalies)
        
        # Convert to response
        result = [
            {
                'id': a.id,
                'timestamp': a.timestamp.isoformat(),
                'metric_name': a.metric_name,
                'actual_value': a.actual_value,
                'expected_value': a.expected_value,
                'deviation': a.deviation,
                'severity': a.severity,
                'confidence': a.confidence,
                'description': a.description,
                'context': a.context
            }
            for a in all_anomalies
        ]
        
        return {
            'anomalies': result,
            'total_metrics': len(metrics),
            'total_anomalies': len(all_anomalies),
            'detection_method': method
        }
        
    except Exception as e:
        logger.error(f"Anomaly detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        'status': 'healthy',
        'service': 'incident-analysis',
        'features': [
            'event_correlation',
            'anomaly_detection',
            'root_cause_analysis',
            'remediation_recommendations'
        ]
    }


@router.get("/demo")
async def get_demo_data():
    """
    Get demo data for testing incident analysis.
    
    Returns sample events and metrics that can be used to test the API.
    """
    demo_events = [
        {
            'timestamp': datetime.utcnow().isoformat(),
            'source': 'prometheus',
            'severity': 'critical',
            'message': 'High CPU usage detected on api-gateway',
            'labels': {'service': 'api-gateway', 'pod': 'api-gateway-7d8f9c-abc123'}
        },
        {
            'timestamp': datetime.utcnow().isoformat(),
            'source': 'kubernetes',
            'severity': 'warning',
            'message': 'Pod api-gateway-7d8f9c-abc123 restarted',
            'labels': {'service': 'api-gateway', 'pod': 'api-gateway-7d8f9c-abc123'}
        },
        {
            'timestamp': datetime.utcnow().isoformat(),
            'source': 'logs',
            'severity': 'critical',
            'message': 'OutOfMemoryError in api-gateway service',
            'labels': {'service': 'api-gateway', 'level': 'error'}
        }
    ]
    
    demo_metrics = [
        {
            'name': 'cpu_usage',
            'timestamp': datetime.utcnow().isoformat(),
            'value': 95.5,
            'labels': {'service': 'api-gateway'}
        },
        {
            'name': 'memory_usage',
            'timestamp': datetime.utcnow().isoformat(),
            'value': 92.3,
            'labels': {'service': 'api-gateway'}
        },
        {
            'name': 'error_rate',
            'timestamp': datetime.utcnow().isoformat(),
            'value': 8.5,
            'labels': {'service': 'api-gateway'}
        }
    ]
    
    return {
        'events': demo_events,
        'metrics': demo_metrics,
        'usage': 'POST these to /incident-analysis/analyze endpoint'
    }
