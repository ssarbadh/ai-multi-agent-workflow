"""Event Correlation Service for Incident Analysis.

Correlates related events across different sources (logs, metrics, alerts)
to identify incident patterns and root causes.
"""

import logging
from typing import List, Dict, Any, Optional, Set
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Represents a system event."""
    id: str
    timestamp: datetime
    source: str  # prometheus, logs, servicenow, etc.
    severity: str  # critical, warning, info
    message: str
    labels: Dict[str, str]
    metadata: Dict[str, Any]


@dataclass
class CorrelatedIncident:
    """Represents a group of correlated events forming an incident."""
    id: str
    events: List[Event]
    root_cause_event: Optional[Event]
    affected_services: Set[str]
    severity: str
    start_time: datetime
    end_time: Optional[datetime]
    correlation_score: float
    summary: str


class EventCorrelator:
    """
    Correlates events using multiple strategies:
    1. Time-based correlation (events within time window)
    2. Service-based correlation (same service/component)
    3. Causality correlation (error propagation patterns)
    4. Pattern-based correlation (similar error messages)
    """
    
    def __init__(
        self,
        time_window_seconds: int = 300,  # 5 minutes
        similarity_threshold: float = 0.7
    ):
        self.time_window = timedelta(seconds=time_window_seconds)
        self.similarity_threshold = similarity_threshold
        self.active_incidents: Dict[str, CorrelatedIncident] = {}
    
    async def correlate_events(
        self,
        events: List[Event]
    ) -> List[CorrelatedIncident]:
        """
        Correlate events into incidents.
        
        Args:
            events: List of events to correlate
            
        Returns:
            List of correlated incidents
        """
        if not events:
            return []
        
        # Sort events by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)
        
        incidents = []
        processed_event_ids = set()
        
        for event in sorted_events:
            if event.id in processed_event_ids:
                continue
            
            # Find related events
            related_events = self._find_related_events(
                event,
                [e for e in sorted_events if e.id not in processed_event_ids]
            )
            
            if related_events:
                # Create incident from correlated events
                incident = self._create_incident([event] + related_events)
                incidents.append(incident)
                
                # Mark events as processed
                for e in [event] + related_events:
                    processed_event_ids.add(e.id)
            else:
                # Single event incident
                incident = self._create_incident([event])
                incidents.append(incident)
                processed_event_ids.add(event.id)
        
        logger.info(f"Correlated {len(events)} events into {len(incidents)} incidents")
        return incidents
    
    def _find_related_events(
        self,
        base_event: Event,
        candidate_events: List[Event]
    ) -> List[Event]:
        """Find events related to the base event."""
        related = []
        
        for event in candidate_events:
            if event.id == base_event.id:
                continue
            
            # Calculate correlation score
            score = self._calculate_correlation_score(base_event, event)
            
            if score >= self.similarity_threshold:
                related.append(event)
        
        return related
    
    def _calculate_correlation_score(
        self,
        event1: Event,
        event2: Event
    ) -> float:
        """Calculate correlation score between two events."""
        score = 0.0
        weights = {
            'time': 0.3,
            'service': 0.3,
            'severity': 0.2,
            'message': 0.2
        }
        
        # Time proximity
        time_diff = abs((event1.timestamp - event2.timestamp).total_seconds())
        if time_diff <= self.time_window.total_seconds():
            time_score = 1.0 - (time_diff / self.time_window.total_seconds())
            score += time_score * weights['time']
        
        # Service/component similarity
        service1 = event1.labels.get('service', event1.labels.get('component', ''))
        service2 = event2.labels.get('service', event2.labels.get('component', ''))
        if service1 and service2 and service1 == service2:
            score += weights['service']
        
        # Severity similarity
        if event1.severity == event2.severity:
            score += weights['severity']
        
        # Message similarity (simple keyword matching)
        message_score = self._calculate_message_similarity(
            event1.message,
            event2.message
        )
        score += message_score * weights['message']
        
        return score
    
    def _calculate_message_similarity(
        self,
        message1: str,
        message2: str
    ) -> float:
        """Calculate similarity between two messages."""
        # Simple keyword-based similarity
        words1 = set(message1.lower().split())
        words2 = set(message2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union) if union else 0.0
    
    def _create_incident(self, events: List[Event]) -> CorrelatedIncident:
        """Create a correlated incident from events."""
        # Sort events by timestamp
        sorted_events = sorted(events, key=lambda e: e.timestamp)
        
        # Identify root cause (first critical event or first event)
        root_cause = next(
            (e for e in sorted_events if e.severity == 'critical'),
            sorted_events[0]
        )
        
        # Extract affected services
        affected_services = set()
        for event in events:
            service = event.labels.get('service') or event.labels.get('component')
            if service:
                affected_services.add(service)
        
        # Determine overall severity
        severity_order = {'critical': 3, 'warning': 2, 'info': 1}
        max_severity = max(
            events,
            key=lambda e: severity_order.get(e.severity, 0)
        ).severity
        
        # Calculate correlation score
        correlation_score = self._calculate_incident_correlation_score(events)
        
        # Generate incident ID
        incident_id = self._generate_incident_id(events)
        
        # Create summary
        summary = self._generate_incident_summary(events, affected_services)
        
        return CorrelatedIncident(
            id=incident_id,
            events=events,
            root_cause_event=root_cause,
            affected_services=affected_services,
            severity=max_severity,
            start_time=sorted_events[0].timestamp,
            end_time=sorted_events[-1].timestamp if len(sorted_events) > 1 else None,
            correlation_score=correlation_score,
            summary=summary
        )
    
    def _calculate_incident_correlation_score(
        self,
        events: List[Event]
    ) -> float:
        """Calculate overall correlation score for incident."""
        if len(events) <= 1:
            return 1.0
        
        # Calculate average pairwise correlation
        total_score = 0.0
        pairs = 0
        
        for i, event1 in enumerate(events):
            for event2 in events[i+1:]:
                total_score += self._calculate_correlation_score(event1, event2)
                pairs += 1
        
        return total_score / pairs if pairs > 0 else 0.0
    
    def _generate_incident_id(self, events: List[Event]) -> str:
        """Generate unique incident ID."""
        # Use hash of event IDs and timestamps
        content = ''.join(f"{e.id}{e.timestamp}" for e in events)
        return f"INC-{hashlib.md5(content.encode()).hexdigest()[:12]}"
    
    def _generate_incident_summary(
        self,
        events: List[Event],
        affected_services: Set[str]
    ) -> str:
        """Generate human-readable incident summary."""
        event_count = len(events)
        services = ', '.join(sorted(affected_services)) if affected_services else 'Unknown'
        
        # Get most common error keywords
        all_words = []
        for event in events:
            all_words.extend(event.message.lower().split())
        
        # Count word frequency (excluding common words)
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
        word_freq = defaultdict(int)
        for word in all_words:
            if word not in stop_words and len(word) > 3:
                word_freq[word] += 1
        
        top_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:3]
        keywords = ', '.join(word for word, _ in top_keywords) if top_keywords else 'system issues'
        
        return f"{event_count} correlated events affecting {services} - Keywords: {keywords}"


# Global instance
event_correlator = EventCorrelator()
