"""Anomaly Detection Service for Incident Analysis.

Detects anomalies in metrics, logs, and system behavior using
statistical methods and machine learning techniques.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import deque
import statistics

logger = logging.getLogger(__name__)


@dataclass
class MetricDataPoint:
    """Represents a metric data point."""
    timestamp: datetime
    value: float
    labels: Dict[str, str]


@dataclass
class Anomaly:
    """Represents a detected anomaly."""
    id: str
    timestamp: datetime
    metric_name: str
    actual_value: float
    expected_value: float
    deviation: float
    severity: str  # critical, warning, info
    confidence: float
    context: Dict[str, Any]
    description: str


class AnomalyDetector:
    """
    Detects anomalies using multiple methods:
    1. Statistical (Z-score, IQR)
    2. Threshold-based
    3. Rate of change
    4. Seasonal patterns
    """
    
    def __init__(
        self,
        z_score_threshold: float = 3.0,
        window_size: int = 100,
        seasonal_period: int = 24  # hours
    ):
        self.z_score_threshold = z_score_threshold
        self.window_size = window_size
        self.seasonal_period = seasonal_period
        
        # Historical data for baseline calculation
        self.metric_history: Dict[str, deque] = {}
    
    async def detect_anomalies(
        self,
        metric_name: str,
        data_points: List[MetricDataPoint],
        method: str = 'statistical'
    ) -> List[Anomaly]:
        """
        Detect anomalies in metric data.
        
        Args:
            metric_name: Name of the metric
            data_points: List of metric data points
            method: Detection method (statistical, threshold, rate_of_change)
            
        Returns:
            List of detected anomalies
        """
        if not data_points:
            return []
        
        anomalies = []
        
        if method == 'statistical':
            anomalies = await self._detect_statistical_anomalies(
                metric_name,
                data_points
            )
        elif method == 'threshold':
            anomalies = await self._detect_threshold_anomalies(
                metric_name,
                data_points
            )
        elif method == 'rate_of_change':
            anomalies = await self._detect_rate_anomalies(
                metric_name,
                data_points
            )
        elif method == 'all':
            # Combine all methods
            stat_anomalies = await self._detect_statistical_anomalies(
                metric_name,
                data_points
            )
            threshold_anomalies = await self._detect_threshold_anomalies(
                metric_name,
                data_points
            )
            rate_anomalies = await self._detect_rate_anomalies(
                metric_name,
                data_points
            )
            
            # Deduplicate and merge
            anomalies = self._merge_anomalies([
                stat_anomalies,
                threshold_anomalies,
                rate_anomalies
            ])
        
        logger.info(
            f"Detected {len(anomalies)} anomalies in {metric_name} "
            f"using {method} method"
        )
        
        return anomalies
    
    async def _detect_statistical_anomalies(
        self,
        metric_name: str,
        data_points: List[MetricDataPoint]
    ) -> List[Anomaly]:
        """Detect anomalies using statistical methods (Z-score)."""
        if len(data_points) < 10:
            return []
        
        anomalies = []
        values = [dp.value for dp in data_points]
        
        # Calculate mean and standard deviation
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0
        
        if stdev == 0:
            return []
        
        # Calculate Z-scores
        for dp in data_points:
            z_score = abs((dp.value - mean) / stdev)
            
            if z_score > self.z_score_threshold:
                # Anomaly detected
                severity = self._calculate_severity(z_score)
                confidence = min(z_score / (self.z_score_threshold * 2), 1.0)
                
                anomaly = Anomaly(
                    id=f"ANOM-{metric_name}-{int(dp.timestamp.timestamp())}",
                    timestamp=dp.timestamp,
                    metric_name=metric_name,
                    actual_value=dp.value,
                    expected_value=mean,
                    deviation=z_score,
                    severity=severity,
                    confidence=confidence,
                    context={
                        'method': 'z_score',
                        'mean': mean,
                        'stdev': stdev,
                        'z_score': z_score,
                        'labels': dp.labels
                    },
                    description=f"{metric_name} value {dp.value:.2f} deviates {z_score:.2f} standard deviations from mean {mean:.2f}"
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    async def _detect_threshold_anomalies(
        self,
        metric_name: str,
        data_points: List[MetricDataPoint]
    ) -> List[Anomaly]:
        """Detect anomalies using predefined thresholds."""
        # Define thresholds for common metrics
        thresholds = {
            'cpu_usage': {'critical': 90, 'warning': 75},
            'memory_usage': {'critical': 90, 'warning': 80},
            'disk_usage': {'critical': 95, 'warning': 85},
            'error_rate': {'critical': 5, 'warning': 1},
            'response_time': {'critical': 5000, 'warning': 2000},  # ms
            'request_rate': {'critical': 10000, 'warning': 5000},
        }
        
        anomalies = []
        
        # Find matching threshold
        threshold_config = None
        for key, config in thresholds.items():
            if key in metric_name.lower():
                threshold_config = config
                break
        
        if not threshold_config:
            return []
        
        for dp in data_points:
            severity = None
            threshold_value = None
            
            if dp.value >= threshold_config.get('critical', float('inf')):
                severity = 'critical'
                threshold_value = threshold_config['critical']
            elif dp.value >= threshold_config.get('warning', float('inf')):
                severity = 'warning'
                threshold_value = threshold_config['warning']
            
            if severity:
                anomaly = Anomaly(
                    id=f"ANOM-{metric_name}-{int(dp.timestamp.timestamp())}",
                    timestamp=dp.timestamp,
                    metric_name=metric_name,
                    actual_value=dp.value,
                    expected_value=threshold_value,
                    deviation=dp.value - threshold_value,
                    severity=severity,
                    confidence=0.95,
                    context={
                        'method': 'threshold',
                        'threshold': threshold_value,
                        'labels': dp.labels
                    },
                    description=f"{metric_name} value {dp.value:.2f} exceeds {severity} threshold {threshold_value:.2f}"
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    async def _detect_rate_anomalies(
        self,
        metric_name: str,
        data_points: List[MetricDataPoint]
    ) -> List[Anomaly]:
        """Detect anomalies based on rate of change."""
        if len(data_points) < 2:
            return []
        
        anomalies = []
        
        # Calculate rate of change between consecutive points
        for i in range(1, len(data_points)):
            prev_dp = data_points[i-1]
            curr_dp = data_points[i]
            
            time_diff = (curr_dp.timestamp - prev_dp.timestamp).total_seconds()
            if time_diff == 0:
                continue
            
            value_diff = curr_dp.value - prev_dp.value
            rate_of_change = abs(value_diff / time_diff)
            
            # Calculate expected rate based on historical data
            expected_rate = self._calculate_expected_rate(metric_name)
            
            # Detect sudden spikes or drops
            if expected_rate > 0 and rate_of_change > expected_rate * 5:
                severity = 'critical' if rate_of_change > expected_rate * 10 else 'warning'
                
                anomaly = Anomaly(
                    id=f"ANOM-{metric_name}-{int(curr_dp.timestamp.timestamp())}",
                    timestamp=curr_dp.timestamp,
                    metric_name=metric_name,
                    actual_value=curr_dp.value,
                    expected_value=prev_dp.value,
                    deviation=rate_of_change,
                    severity=severity,
                    confidence=0.85,
                    context={
                        'method': 'rate_of_change',
                        'rate': rate_of_change,
                        'expected_rate': expected_rate,
                        'labels': curr_dp.labels
                    },
                    description=f"{metric_name} changed rapidly from {prev_dp.value:.2f} to {curr_dp.value:.2f} (rate: {rate_of_change:.2f}/s)"
                )
                anomalies.append(anomaly)
        
        return anomalies
    
    def _calculate_severity(self, z_score: float) -> str:
        """Calculate severity based on Z-score."""
        if z_score > self.z_score_threshold * 2:
            return 'critical'
        elif z_score > self.z_score_threshold * 1.5:
            return 'warning'
        else:
            return 'info'
    
    def _calculate_expected_rate(self, metric_name: str) -> float:
        """Calculate expected rate of change from historical data."""
        if metric_name not in self.metric_history:
            return 1.0  # Default
        
        history = list(self.metric_history[metric_name])
        if len(history) < 2:
            return 1.0
        
        # Calculate average rate of change
        rates = []
        for i in range(1, len(history)):
            rate = abs(history[i] - history[i-1])
            rates.append(rate)
        
        return statistics.mean(rates) if rates else 1.0
    
    def _merge_anomalies(
        self,
        anomaly_lists: List[List[Anomaly]]
    ) -> List[Anomaly]:
        """Merge anomalies from different detection methods."""
        # Use timestamp and metric as key for deduplication
        anomaly_map = {}
        
        for anomalies in anomaly_lists:
            for anomaly in anomalies:
                key = f"{anomaly.metric_name}-{int(anomaly.timestamp.timestamp())}"
                
                if key not in anomaly_map:
                    anomaly_map[key] = anomaly
                else:
                    # Keep the one with higher confidence
                    if anomaly.confidence > anomaly_map[key].confidence:
                        anomaly_map[key] = anomaly
        
        return list(anomaly_map.values())
    
    def update_baseline(
        self,
        metric_name: str,
        value: float
    ):
        """Update baseline data for a metric."""
        if metric_name not in self.metric_history:
            self.metric_history[metric_name] = deque(maxlen=self.window_size)
        
        self.metric_history[metric_name].append(value)


# Global instance
anomaly_detector = AnomalyDetector()
