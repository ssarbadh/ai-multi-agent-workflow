"""Agent evaluation metrics calculator per HLD requirements."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from statistics import mean, median
import numpy as np

from app.models.schemas import (
    AgentEvaluationMetrics, TaskOutcomeMetrics, 
    InteractionSafetyMetrics, EfficiencyMetrics
)

logger = logging.getLogger(__name__)


class AgentEvaluator:
    """
    Calculates agent evaluation metrics per HLD.
    
    Task/Outcome:
    - Resolution Rate, Time to Resolution, First-Action Success Rate
    - Rollback Rate, Escalation Rate, Approval Compliance
    
    Interaction & Safety:
    - User Satisfaction, Feedback Utilization, Confidentiality Accuracy
    - Safety Incidents
    
    Efficiency:
    - Steps per Resolution, Tool Success Rate, Reattempts per Tool Call
    - Human Wait Time
    """
    
    def __init__(self, db_session=None):
        self.db = db_session
    
    async def calculate_metrics(
        self,
        period_hours: int = 24,
        agent_type: Optional[str] = None
    ) -> AgentEvaluationMetrics:
        """Calculate all agent evaluation metrics for the given period."""
        
        # In production, these would query the database
        # For now, return calculated metrics from available data
        
        task_outcome = await self._calculate_task_outcome_metrics(period_hours, agent_type)
        interaction_safety = await self._calculate_interaction_safety_metrics(period_hours)
        efficiency = await self._calculate_efficiency_metrics(period_hours, agent_type)
        
        return AgentEvaluationMetrics(
            timestamp=datetime.now(timezone.utc),
            period_hours=period_hours,
            task_outcome=task_outcome,
            interaction_safety=interaction_safety,
            efficiency=efficiency
        )
    
    async def _calculate_task_outcome_metrics(
        self,
        period_hours: int,
        agent_type: Optional[str]
    ) -> TaskOutcomeMetrics:
        """Calculate task/outcome metrics."""
        
        # Query agent run metrics from database
        # SELECT status, duration_seconds, was_escalated, was_rolled_back, 
        #        first_action_success, approvals_count
        # FROM agent_run_metrics
        # WHERE started_at > NOW() - INTERVAL period_hours HOUR
        
        # Placeholder calculations - in production, query actual data
        runs_data = await self._get_agent_runs(period_hours, agent_type)
        
        if not runs_data:
            return TaskOutcomeMetrics(
                resolution_rate=0.0,
                time_to_resolution_p50=0.0,
                time_to_resolution_p95=0.0,
                first_action_success_rate=0.0,
                rollback_rate=0.0,
                escalation_rate=0.0,
                approval_compliance=1.0
            )
        
        total_runs = len(runs_data)
        resolved_runs = [r for r in runs_data if r.get("status") == "completed"]
        resolution_times = [r.get("duration_seconds", 0) / 60 for r in resolved_runs]
        
        # Calculate percentiles
        if resolution_times:
            time_p50 = float(np.percentile(resolution_times, 50))
            time_p95 = float(np.percentile(resolution_times, 95))
        else:
            time_p50 = time_p95 = 0.0
        
        escalated = sum(1 for r in runs_data if r.get("was_escalated"))
        rolled_back = sum(1 for r in runs_data if r.get("was_rolled_back"))
        first_success = sum(1 for r in runs_data if r.get("first_action_success"))
        
        # Approval compliance: runs requiring approval that got it
        runs_with_approvals = [r for r in runs_data if r.get("approvals_count", 0) > 0]
        approval_compliance = 1.0  # Assume compliant if approval was recorded
        
        return TaskOutcomeMetrics(
            resolution_rate=len(resolved_runs) / total_runs if total_runs > 0 else 0.0,
            time_to_resolution_p50=time_p50,
            time_to_resolution_p95=time_p95,
            first_action_success_rate=first_success / total_runs if total_runs > 0 else 0.0,
            rollback_rate=rolled_back / total_runs if total_runs > 0 else 0.0,
            escalation_rate=escalated / total_runs if total_runs > 0 else 0.0,
            approval_compliance=approval_compliance
        )
    
    async def _calculate_interaction_safety_metrics(
        self,
        period_hours: int
    ) -> InteractionSafetyMetrics:
        """Calculate interaction & safety metrics."""
        
        # Query feedback and safety data
        feedback_data = await self._get_feedback_data(period_hours)
        safety_data = await self._get_safety_incidents(period_hours)
        
        # Calculate user satisfaction from thumbs up/down
        if feedback_data:
            up_count = sum(1 for f in feedback_data if f.get("feedback") == "up")
            down_count = sum(1 for f in feedback_data if f.get("feedback") == "down")
            total_feedback = up_count + down_count
            satisfaction = up_count / total_feedback if total_feedback > 0 else 0.5
        else:
            satisfaction = 0.5
        
        # Feedback utilization: sessions where preferences changed behavior
        sessions_with_preference_effect = sum(
            1 for f in feedback_data if f.get("effect_applied")
        ) if feedback_data else 0
        total_sessions = len(set(f.get("session_id") for f in feedback_data)) if feedback_data else 1
        
        return InteractionSafetyMetrics(
            user_satisfaction_avg=satisfaction,
            csat_score=None,  # Would come from surveys
            feedback_utilization=sessions_with_preference_effect / total_sessions if total_sessions > 0 else 0.0,
            confidentiality_accuracy=0.95,  # Would compare computed vs reviewed labels
            safety_incidents=len(safety_data) if safety_data else 0
        )
    
    async def _calculate_efficiency_metrics(
        self,
        period_hours: int,
        agent_type: Optional[str]
    ) -> EfficiencyMetrics:
        """Calculate efficiency metrics."""
        
        runs_data = await self._get_agent_runs(period_hours, agent_type)
        tool_data = await self._get_tool_calls(period_hours)
        
        # Steps per resolution
        steps = [r.get("steps_count", 0) for r in runs_data if r.get("status") == "completed"]
        steps_mean = mean(steps) if steps else 0.0
        steps_median = median(steps) if steps else 0.0
        
        # Tool success rate
        if tool_data:
            successful_tools = sum(1 for t in tool_data if t.get("outcome") == "ok")
            tool_success_rate = successful_tools / len(tool_data)
            
            # Reattempts per tool call
            total_retries = sum(t.get("retries", 0) for t in tool_data)
            reattempts = total_retries / len(tool_data)
        else:
            tool_success_rate = 1.0
            reattempts = 0.0
        
        # Human wait time (approval/password waits)
        wait_times = [r.get("approval_wait_seconds", 0) for r in runs_data if r.get("approval_wait_seconds", 0) > 0]
        if wait_times:
            wait_p50 = float(np.percentile(wait_times, 50))
            wait_p95 = float(np.percentile(wait_times, 95))
        else:
            wait_p50 = wait_p95 = 0.0
        
        return EfficiencyMetrics(
            steps_per_resolution_mean=steps_mean,
            steps_per_resolution_median=steps_median,
            tool_success_rate=tool_success_rate,
            reattempts_per_tool_call=reattempts,
            human_wait_time_p50=wait_p50,
            human_wait_time_p95=wait_p95
        )
    
    # Data access methods - would query database in production
    async def _get_agent_runs(self, period_hours: int, agent_type: Optional[str]) -> List[Dict]:
        """Get agent run data from database."""
        # Placeholder - would query agent_run_metrics table
        return []
    
    async def _get_feedback_data(self, period_hours: int) -> List[Dict]:
        """Get feedback data from database."""
        # Placeholder - would query feedback records
        return []
    
    async def _get_safety_incidents(self, period_hours: int) -> List[Dict]:
        """Get safety incident data."""
        # Placeholder - would query safety incident logs
        return []
    
    async def _get_tool_calls(self, period_hours: int) -> List[Dict]:
        """Get tool call data from database."""
        # Placeholder - would query tool call logs
        return []


# Global instance
agent_evaluator = AgentEvaluator()
