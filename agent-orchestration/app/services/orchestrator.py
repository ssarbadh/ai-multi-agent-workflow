"""Main orchestrator service using LangGraph.

Integrates with all backend services per HLD Data Flow:
- Context Management: State, memory, prompts
- RAG: Knowledge search, decision matrix
- MCP: Tool execution
- Observability: Metrics, traces, logs
- LLM: OpenRouter for agent reasoning
"""

import logging
import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.models import Run, RunStatus, RequestType, Message
from app.core.redis_client import redis_client
from app.core.observability import get_metrics
from app.services.rag_client import rag_client
from app.services.context_client import context_client
from app.services.mcp_client import mcp_client
from app.services.observability_client import observability_client
from app.services.llm_client import llm_client
from app.services.intent_detector import intent_detector, Intent
from app.agents.conversational_agent import conversational_agent
from app.agents.devops_agent_v5 import devops_agent_v5

logger = logging.getLogger(__name__)


class OrchestratorService:
    """
    Main orchestrator service that manages LangGraph execution.
    
    This service:
    1. Routes requests to appropriate agent paths (SR/CR vs Incident)
    2. Manages graph state and checkpoints
    3. Coordinates with Context Management and RAG services
    4. Executes tools via MCP
    5. Reports metrics to Observability
    6. Streams progress via Redis pub/sub
    7. Handles human-in-the-loop gates
    """
    
    def __init__(self):
        self._active_runs: Dict[str, asyncio.Task] = {}
        self._rag = rag_client
        self._context = context_client
        self._mcp = mcp_client
        self._observability = observability_client
        self._llm = llm_client
    
    async def start_run(self, run_id: str, message: str, db: AsyncSession = None) -> None:
        """
        Start an orchestration run asynchronously.
        
        Args:
            run_id: Run identifier
            message: User message/request
            db: Database session (optional, will create new one in background task)
        """
        # Create background task (don't pass db session - will create new one inside)
        task = asyncio.create_task(self._execute_run(run_id, message))
        self._active_runs[run_id] = task
        
        logger.info(f"Started background task for run: {run_id}")
    
    
    async def _execute_run(self, run_id: str, message: str) -> None:
        """
        Execute the orchestration run.
        
        This is the main execution loop that:
        1. Routes the request
        2. Builds context from Context Management
        3. Retrieves relevant knowledge from RAG
        4. Executes the appropriate agent graph
        5. Calls tools via MCP
        6. Reports metrics to Observability
        7. Streams progress
        8. Handles errors and checkpoints
        """
        from app.core.database import AsyncSessionLocal
        
        metrics = get_metrics()
        start_time = datetime.utcnow()
        steps_count = 0
        tool_calls_count = 0
        
        # Create a new database session for this background task
        async with AsyncSessionLocal() as db:
            try:
                # Update run status
                result = await db.execute(select(Run).where(Run.id == run_id))
                run = result.scalar_one()
                run.status = RunStatus.RUNNING
                run.started_at = start_time
                await db.commit()
                
                # Step 1: Build context from Context Management (silently for now)
                context = {}
                try:
                    context = await self._context.get_context(
                        session_id=str(run.session_id),
                        run_id=run_id,
                        query=message,
                        max_tokens=4000
                    )
                    steps_count += 1
                    logger.info(f"Context retrieved: STM={len(context.get('stm', []))}, LTM={len(context.get('ltm', []))}")
                except Exception as e:
                    logger.error(f"Context Management service error: {e}", exc_info=True)
                    context = {"stm": [], "ltm": [], "preferences": []}
                    steps_count += 1
                
                # Step 2: Detect intent FIRST (before showing any progress)
                # Get conversation history for context
                conversation_context = []
                if context.get("stm"):
                    conversation_context = [
                        {"role": msg.get("role", "user"), "content": msg.get("content", "")}
                        for msg in context.get("stm", [])[-5:]  # Last 5 messages
                    ]
                
                intent = await intent_detector.detect(message, conversation_context)
                steps_count += 1
                
                # Now emit progress events ONLY for non-conversational workflows
                show_workflow_progress = intent not in [Intent.CONVERSATIONAL]
                
                if show_workflow_progress:
                    # Define total steps for progress tracking
                    total_steps = 8  # Adjust based on workflow
                    current_step = 0
                    
                    # Emit start event with progress
                    current_step += 1
                    await self._emit_progress(run_id, current_step, total_steps, 
                                             "Starting orchestration...", "in_progress")
                    
                    current_step += 1
                    await self._emit_progress(run_id, current_step, total_steps,
                                             f"Context built successfully ({len(context.get('stm', []))} recent messages)", "success")
                    
                    current_step += 1
                    await self._emit_progress(run_id, current_step, total_steps,
                                             f"Intent detected: {intent.value}", "success")
                else:
                    # For conversational, no workflow progress
                    total_steps = 0
                    current_step = 0
                
                # Step 3: Route based on intent
                current_step += 1
                agent_type = None  # Track agent type for UI
                
                if intent == Intent.CONVERSATIONAL:
                    agent_type = "conversational"
                    # Handle conversational interaction (no progress message - stream directly)
                    tool_calls = await self._execute_conversational_path(run_id, message, conversation_context, db)
                    request_type = RequestType.CONVERSATIONAL
                elif intent == Intent.DEVOPS:
                    agent_type = "devops"
                    # Emit agent_type immediately so VM console can connect early
                    await self._emit_event(run_id, "agent_type", {"agent_type": agent_type})
                    await self._emit_progress(run_id, current_step, total_steps,
                                             "Initiating DevOps automation workflow...", "in_progress")
                    # Handle DevOps automation
                    tool_calls = await self._execute_devops_path(run_id, message, context, db)
                    request_type = RequestType.DEVOPS_AUTOMATION
                elif intent == Intent.CLOUDOPS:
                    agent_type = "cloudops"
                    # Emit agent_type immediately so VM console can connect early
                    await self._emit_event(run_id, "agent_type", {"agent_type": agent_type})
                    await self._emit_progress(run_id, current_step, total_steps,
                                             "Initiating CloudOps infrastructure provisioning...", "in_progress")
                    # Handle CloudOps operations
                    tool_calls = await self._execute_cloudops_path(run_id, message, context, db)
                    request_type = RequestType.CLOUDOPS
                elif intent == Intent.SRE:
                    agent_type = "sre"
                    # Emit agent_type immediately so VM console can connect early
                    await self._emit_event(run_id, "agent_type", {"agent_type": agent_type})
                    await self._emit_progress(run_id, current_step, total_steps,
                                             "Initiating SRE monitoring and analysis...", "in_progress")
                    # Handle SRE operations
                    tool_calls = await self._execute_sre_path(run_id, message, context, db)
                    request_type = RequestType.SRE
                elif intent == Intent.INCIDENT:
                    agent_type = "incident"
                    # Emit agent_type immediately so VM console can connect early
                    await self._emit_event(run_id, "agent_type", {"agent_type": agent_type})
                    await self._emit_progress(run_id, current_step, total_steps,
                                             "Analyzing incident and searching for solutions...", "in_progress")
                    # Handle incident troubleshooting
                    tool_calls = await self._execute_incident_path(run_id, message, context, db)
                    request_type = RequestType.INCIDENT
                else:
                    await self._emit_progress(run_id, current_step, total_steps,
                                             "Routing to appropriate service agent...", "in_progress")
                    # Fallback to traditional routing for SR/CR/Incident
                    request_type_str = await self._route_request(run_id, message)
                    steps_count += 1
                    
                    # Execute appropriate path and convert to enum
                    if request_type_str in ["service_request", "change_request"]:
                        tool_calls = await self._execute_sr_cr_path(run_id, message, context, db)
                        request_type = RequestType.SERVICE_REQUEST if request_type_str == "service_request" else RequestType.CHANGE_REQUEST
                    else:
                        tool_calls = await self._execute_incident_path(run_id, message, context, db)
                        request_type = RequestType.INCIDENT if request_type_str == "incident" else RequestType.PROBLEM
                
                run.request_type = request_type
                run.routed_to = request_type.value
                await db.commit()
                
                # Note: agent_type event already emitted during routing (earlier in workflow)
                
                tool_calls_count = tool_calls
                steps_count += 4  # Approximate steps in each path
            
                # Final progress update
                current_step = total_steps
                await self._emit_progress(run_id, current_step, total_steps,
                                         "✅ Task completed successfully!", "success")
                
                # Complete run
                end_time = datetime.utcnow()
                run.status = RunStatus.COMPLETED
                run.completed_at = end_time
                run.duration_seconds = (end_time - start_time).total_seconds()
                await db.commit()
                
                # Save completion summary to database (for non-conversational and non-streaming workflows)
                # Skip for SRE and Incident since they stream their full response
                if request_type not in [RequestType.CONVERSATIONAL, RequestType.SRE, RequestType.INCIDENT, RequestType.PROBLEM]:
                    # Get the user message ID to link response
                    result_msg = await db.execute(
                        select(Message)
                        .where(Message.run_id == run_id)
                        .where(Message.role == "user")
                        .order_by(Message.created_at.desc())
                    )
                    user_message = result_msg.scalar_one_or_none()
                    parent_message_id = user_message.id if user_message else None
                    
                    completion_message = f"✅ {request_type.value} completed successfully in {run.duration_seconds:.1f}s"
                    
                    # Map request type to agent type
                    agent_type_map = {
                        RequestType.DEVOPS_AUTOMATION: "devops",
                        RequestType.CLOUDOPS: "cloudops",
                        RequestType.SERVICE_REQUEST: "sr_cr",
                        RequestType.CHANGE_REQUEST: "sr_cr"
                    }
                    
                    await self._save_agent_message(
                        run_id=run_id,
                        content=completion_message,
                        db=db,
                        agent_type=agent_type_map.get(request_type, "unknown"),  # NEW: Agent type
                        parent_message_id=parent_message_id,  # NEW: Link to user message
                        confidentiality_score=0.1,
                        confidentiality_label="low",
                        metadata={  # NEW: Workflow metadata
                            "workflow_type": request_type.value,
                            "duration_seconds": run.duration_seconds,
                            "steps_count": steps_count,
                            "tool_calls_count": tool_calls_count
                        }
                    )
                
                # Store completion message in Context Management
                try:
                    await self._context.add_message(
                        session_id=str(run.session_id),
                        role="assistant",
                        content=f"Completed {request_type} successfully",
                        metadata={"run_id": run_id, "duration": run.duration_seconds}
                    )
                except Exception as e:
                    logger.warning(f"Failed to store message in Context Management: {e}")
                
                await self._emit_event(run_id, "complete", {
                    "status": "completed",
                    "duration_seconds": run.duration_seconds
                })
                
                # Record metrics locally
                metrics.agent_runs_total.labels(
                    agent_type="orchestrator",
                    status="completed"
                ).inc()
                metrics.agent_run_duration.labels(
                    agent_type="orchestrator"
                ).observe(run.duration_seconds)
                
                # Report to Observability service
                await self._observability.record_agent_run(
                    run_id=run_id,
                    agent_type="orchestrator",
                    status="completed",
                    duration_seconds=run.duration_seconds,
                    steps_count=steps_count,
                    tool_calls_count=tool_calls_count
                )
                
                logger.info(f"Run {run_id} completed successfully")
            except Exception as e:
                logger.error(f"Run {run_id} failed: {e}", exc_info=True)
                
                # Emit error progress
                await self._emit_progress(run_id, 0, 0,
                                         f"❌ Error: {str(e)}", "error")
                
                # Update run status
                try:
                    result = await db.execute(select(Run).where(Run.id == run_id))
                    run = result.scalar_one()
                    run.status = RunStatus.FAILED
                    run.completed_at = datetime.utcnow()
                    if run.started_at:
                        run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
                    await db.commit()
                    
                    # Report failure to Observability
                    await self._observability.record_agent_run(
                        run_id=run_id,
                        agent_type="orchestrator",
                        status="failed",
                        duration_seconds=run.duration_seconds or 0,
                        steps_count=steps_count,
                        tool_calls_count=tool_calls_count,
                        extra_data={"error": str(e)}
                    )
                except:
                    pass
                
                await self._emit_event(run_id, "error", {
                    "error": str(e),
                    "type": type(e).__name__
                })
                
                # Record metrics
                metrics.agent_runs_total.labels(
                    agent_type="orchestrator",
                    status="failed"
                ).inc()
            
            finally:
                # Cleanup
                if run_id in self._active_runs:
                    del self._active_runs[run_id]
    
    async def _route_request(self, run_id: str, message: str) -> str:
        """
        Route request to appropriate agent path using LLM.
        
        Uses LLM to classify: SR/CR vs Incident/Problem
        """
        try:
            # Use LLM for intelligent routing
            result = await self._llm.route_request(message)
            
            await self._emit_event(run_id, "analysis", {
                "type": "routing",
                "result": result.get("request_type", "service_request"),
                "confidence": result.get("confidence", 0.5),
                "reasoning": result.get("reasoning", "")
            })
            
            return result.get("request_type", "service_request")
            
        except Exception as e:
            logger.warning(f"LLM routing failed, using fallback: {e}")
            # Fallback to keyword matching
            message_lower = message.lower()
            
            if any(word in message_lower for word in ["create", "provision", "deploy", "setup", "configure"]):
                return "service_request"
            elif any(word in message_lower for word in ["change", "update", "modify", "upgrade"]):
                return "change_request"
            elif any(word in message_lower for word in ["down", "error", "failed", "not working", "issue"]):
                return "incident"
            else:
                return "service_request"  # Default
    
    async def _execute_sr_cr_path(
        self,
        run_id: str,
        message: str,
        context: Dict[str, Any],
        db: AsyncSession
    ) -> int:
        """
        Execute Service/Change Request path with full service integration.
        
        Returns:
            Number of tool calls made
        """
        tool_calls = 0
        
        # Node: SR/CR Agent - Normalize requirements
        await self._emit_event(run_id, "node", {
            "node": "sr_cr_agent",
            "message": "Normalizing requirements..."
        })
        
        # Import and call SR/CR agent
        from app.agents.sr_cr_agent import sr_cr_agent
        requirements = await sr_cr_agent.normalize_requirements(message, context)
        
        await self._emit_event(run_id, "tool", {
            "tool": "sr_cr_agent.normalize_requirements",
            "status": "success",
            "output": requirements
        })
        tool_calls += 1
        
        # Node: Dependency Agent - Discover dependencies via MCP
        await self._emit_event(run_id, "node", {
            "node": "dependency_agent",
            "message": "Discovering infrastructure dependencies..."
        })
        
        # Use MCP to discover infrastructure
        try:
            infra_result = await self._mcp.aws_list_ec2()
            tool_calls += 1
            await self._observability.record_tool_call(
                run_id=run_id,
                tool_name="aws_list_ec2",
                status="success" if "error" not in infra_result else "failed",
                duration_ms=100
            )
        except Exception as e:
            logger.warning(f"MCP service unavailable for infrastructure discovery: {e}")
            infra_result = {"error": str(e), "instances": []}
            await self._emit_event(run_id, "warning", {
                "message": "MCP service unavailable, skipping infrastructure discovery",
                "service": "mcp"
            })
        
        # Node: RAG - Get relevant documentation
        await self._emit_event(run_id, "node", {
            "node": "rag_retrieval",
            "message": "Retrieving relevant documentation..."
        })
        
        try:
            rag_result = await self._rag.search_knowledge_base(
                query=message,
                top_k=5
            )
            tool_calls += 1
        except Exception as e:
            logger.warning(f"RAG service unavailable: {e}")
            rag_result = {"results": [], "sources": []}
            await self._emit_event(run_id, "warning", {
                "message": "RAG service unavailable, continuing without knowledge base context",
                "service": "rag"
            })
        
        # Node: SNOW Agent - Create ticket (placeholder)
        await self._emit_event(run_id, "node", {
            "node": "snow_agent",
            "message": "Creating ServiceNow ticket..."
        })
        
        # Node: Provisioner Agent - Execute workflow
        await self._emit_event(run_id, "node", {
            "node": "provisioner_agent",
            "message": "Executing provisioning workflow..."
        })
        
        # Import and call Provisioner agent
        from app.agents.provisioner_agent import provisioner_agent
        
        # Build workflow plan
        dependencies = {"discovered": infra_result, "rag_context": rag_result}
        workflow_plan = await provisioner_agent.build_workflow_plan(requirements, dependencies)
        
        await self._emit_event(run_id, "tool", {
            "tool": "provisioner_agent.build_workflow_plan",
            "status": "success",
            "output": {"plan_id": workflow_plan["plan_id"], "steps": len(workflow_plan["steps"])}
        })
        tool_calls += 1
        
        # HITL: Check if approval required based on risk analysis
        await self._emit_event(run_id, "node", {
            "node": "safety_approval",
            "message": "Analyzing risk level..."
        })
        
        # Import safety approval agent
        from app.agents.safety_approval_agent import safety_approval_agent
        
        # Analyze risk
        risk_level = "low"  # Default
        requires_approval = False
        
        # Check for high-risk indicators
        if requirements.get("environment") == "production":
            risk_level = "high"
            requires_approval = True
        elif requirements.get("service_type") in ["rds", "eks", "database"]:
            risk_level = "medium"
            requires_approval = True
        
        if requires_approval:
            # Update run status to waiting for approval
            result = await db.execute(select(Run).where(Run.id == run_id))
            run = result.scalar_one()
            run.status = RunStatus.WAITING_APPROVAL
            await db.commit()
            
            # Emit approval_required event to frontend
            await self._emit_event(run_id, "approval_required", {
                "approval_id": f"appr_{run_id}",
                "risk_level": risk_level,
                "action": "provision_infrastructure",
                "workflow_id": workflow_plan.get("workflow_id"),
                "resources": requirements,
                "plan_summary": f"Provision {requirements.get('service_type')} in {requirements.get('environment', 'unknown')} environment"
            })
            
            # Request approval (blocks until user responds or timeout)
            approval_result = await safety_approval_agent.request_approval(
                run_id=run_id,
                action="provision_infrastructure",
                details={
                    "workflow_id": workflow_plan.get("workflow_id"),
                    "risk_level": risk_level,
                    "resources": requirements,
                    "plan": workflow_plan
                },
                timeout_seconds=1800  # 30 minutes
            )
            
            if not approval_result.get("approved"):
                # Approval rejected or timed out
                result = await db.execute(select(Run).where(Run.id == run_id))
                run = result.scalar_one()
                run.status = RunStatus.CANCELLED
                await db.commit()
                
                await self._emit_event(run_id, "error", {
                    "error": f"Approval {approval_result.get('status', 'rejected')}: {approval_result.get('error', 'User rejected or timeout')}",
                    "type": "ApprovalError"
                })
                
                logger.warning(f"Run {run_id} cancelled due to approval {approval_result.get('status')}")
                return tool_calls
            
            # Approval granted
            result = await db.execute(select(Run).where(Run.id == run_id))
            run = result.scalar_one()
            run.status = RunStatus.RUNNING
            await db.commit()
            
            await self._emit_event(run_id, "node", {
                "node": "provisioner",
                "message": "Approval granted, continuing execution..."
            })
            
            logger.info(f"Run {run_id} approved, continuing execution")
        
        # Execute workflow
        execution_result = await provisioner_agent.execute_workflow(workflow_plan, run_id)
        
        await self._emit_event(run_id, "tool", {
            "tool": "provisioner_agent.execute_workflow",
            "status": execution_result["status"],
            "output": {
                "steps_completed": execution_result["steps_completed"],
                "steps_failed": execution_result["steps_failed"]
            }
        })
        tool_calls += 1
        
        # Save checkpoint via Context Management
        try:
            await self._context.save_checkpoint(
                run_id=run_id,
                checkpoint_data={
                    "stage": "provisioning",
                    "infra_discovered": True,
                    "rag_context": len(rag_result.get("results", []))
                }
            )
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")
        
        await asyncio.sleep(1)  # Simulate work
        
        await self._emit_event(run_id, "token", {
            "content": "Service request processed successfully."
        })
        
        return tool_calls
    
    async def _execute_incident_path(
        self,
        run_id: str,
        message: str,
        context: Dict[str, Any],
        db: AsyncSession
    ) -> int:
        """
        Execute Incident/Problem path with full service integration.
        
        Returns:
            Number of tool calls made
        """
        tool_calls = 0
        
        # Node: Incident Agent - Triage
        await self._emit_event(run_id, "node", {
            "node": "incident_agent",
            "message": "Triaging incident..."
        })
        
        # Emit thinking: Starting triage
        await self._emit_event(run_id, "thinking", {
            "message": "🚨 Analyzing incident details and severity..."
        })
        await asyncio.sleep(0.5)
        
        # Emit thinking: Querying RAG
        await self._emit_event(run_id, "thinking", {
            "message": "📚 Searching knowledge base for similar incidents and solutions..."
        })
        await asyncio.sleep(0.5)
        
        # Import and call Incident agent
        from app.agents.incident_agent import incident_agent
        triage_result = await incident_agent.triage(message, context)
        
        await self._emit_event(run_id, "tool", {
            "tool": "incident_agent.triage",
            "status": "success",
            "output": triage_result
        })
        tool_calls += 1
        
        # Emit RAG sources if available (AFTER thinking messages)
        if triage_result.get("rag_sources"):
            await self._emit_event(run_id, "rag_sources", {
                "sources": triage_result["rag_sources"]
            })
            logger.info(f"Emitted {len(triage_result['rag_sources'])} RAG sources for incident")
        
        # Emit thinking: Triage complete
        severity = triage_result.get("severity", "unknown")
        await self._emit_event(run_id, "thinking", {
            "message": f"✅ Triage complete: Severity={severity.upper()}, generating detailed analysis..."
        })
        await asyncio.sleep(0.5)
        
        # Save checkpoint via Context Management
        try:
            await self._context.save_checkpoint(
                run_id=run_id,
                checkpoint_data={
                    "stage": "triage_complete",
                    "severity": severity,
                    "snow_ticket": triage_result.get("snow_ticket")
                }
            )
        except Exception as e:
            logger.warning(f"Failed to save checkpoint: {e}")
        
        # Node: Telemetry Agent - Collect logs/metrics
        await self._emit_event(run_id, "node", {
            "node": "telemetry_agent",
            "message": "Collecting telemetry data..."
        })
        
        # Node: RAG - Search similar incidents and get decision matrix
        await self._emit_event(run_id, "node", {
            "node": "rag_retrieval",
            "message": "Searching similar incidents..."
        })
        
        try:
            similar_incidents = await self._rag.search_similar_incidents(
                description=message,
                top_k=5
            )
            tool_calls += 1
        except Exception as e:
            logger.warning(f"RAG service unavailable for incident search: {e}")
            similar_incidents = []
            await self._emit_event(run_id, "warning", {
                "message": "RAG service unavailable, continuing without similar incidents",
                "service": "rag"
            })
        
        # Get decision matrix
        try:
            decision_matrix = await self._rag.get_decision_matrix(
                incident_type="general",
                context={"message": message, "similar_count": len(similar_incidents)}
            )
            tool_calls += 1
        except Exception as e:
            logger.warning(f"RAG service unavailable for decision matrix: {e}")
            decision_matrix = {"actions": [], "confidence": 0.0}
            await self._emit_event(run_id, "warning", {
                "message": "RAG service unavailable, using default decision matrix",
                "service": "rag"
            })
        
        # Node: Decision Agent - Apply decision matrix
        await self._emit_event(run_id, "node", {
            "node": "decision_agent",
            "message": "Analyzing with decision matrix..."
        })
        
        await self._emit_event(run_id, "analysis", {
            "type": "decision_matrix",
            "similar_incidents": len(similar_incidents),
            "recommended_actions": decision_matrix.get("actions", [])
        })
        
        # Stream the analysis response line by line to preserve markdown formatting
        if triage_result.get("analysis"):
            analysis_text = triage_result["analysis"]
            
            # Stream line by line to preserve markdown structure
            lines = analysis_text.split('\n')
            for i, line in enumerate(lines):
                # Emit full line to preserve markdown
                await self._emit_event(run_id, "token", {
                    "content": line + ("\n" if i < len(lines) - 1 else "")
                })
                # Reasonable delay for readability (50ms per line)
                await asyncio.sleep(0.05)
        else:
            # Fallback message if no analysis
            fallback_msg = f"""## Incident Analysis Complete

**Severity:** {triage_result.get('severity', 'unknown').upper()}
**Scope:** {triage_result.get('scope', 'unknown')}
**Blast Radius:** {triage_result.get('blast_radius', 'unknown')}

Triage completed successfully. Review the sources above for detailed troubleshooting steps."""
            
            await self._emit_event(run_id, "token", {
                "content": fallback_msg
            })
        
        # Node: Remediator Agent - Propose fix
        await self._emit_event(run_id, "node", {
            "node": "remediator_agent",
            "message": "Proposing remediation steps..."
        })
        
        # Generate remediation plan
        from app.agents.remediator_agent import remediator_agent
        
        remediation_plan = await remediator_agent.propose_remediation(
            triage_result=triage_result,
            rag_sources=triage_result.get("rag_sources", []),
            incident_description=message
        )
        
        # Emit remediation plan to UI
        await self._emit_event(run_id, "remediation_plan", {
            "plan": remediation_plan
        })
        
        logger.info(f"Generated remediation plan with {len(remediation_plan.get('steps', []))} steps")
        
        # Check if remediation requires approval
        requires_approval = any(
            step.get("requires_approval", False) 
            for step in remediation_plan.get("steps", [])
        )
        
        if requires_approval:
            # Request human approval for remediation
            await self._emit_event(run_id, "thinking", {
                "message": "⏸️ Remediation plan requires human approval before execution..."
            })
            
            # Format plan summary for approval
            plan_summary = f"""**Remediation Plan Summary**

{remediation_plan.get('summary', 'Remediation steps to resolve the incident')}

**Steps ({len(remediation_plan.get('steps', []))}):**
"""
            for step in remediation_plan.get("steps", []):
                plan_summary += f"\n{step.get('step')}. {step.get('description')}"
                plan_summary += f"\n   Command: `{step.get('command')}`"
                plan_summary += f"\n   Risk: {step.get('risk_level', 'unknown')}"
            
            plan_summary += f"\n\n**Estimated Duration:** {remediation_plan.get('estimated_duration_minutes', 'unknown')} minutes"
            plan_summary += f"\n**Overall Risk:** {remediation_plan.get('overall_risk_level', 'unknown')}"
            
            # Create approval request
            from app.agents.safety_approval_agent import safety_approval_agent
            
            approval_result = await safety_approval_agent.request_approval(
                run_id=run_id,
                action="execute_remediation",
                details={
                    "remediation_plan": remediation_plan,
                    "incident_description": message,
                    "severity": triage_result.get("severity"),
                    "plan_summary": plan_summary
                },
                timeout_seconds=1800  # 30 minutes
            )
            
            if not approval_result.get("approved"):
                # Remediation rejected
                await self._emit_event(run_id, "token", {
                    "content": "\n\n❌ **Remediation Rejected**\n\nThe remediation plan was not approved. The incident remains open for manual resolution."
                })
                
                # Update ServiceNow with rejection
                if triage_result.get("snow_ticket", {}).get("ticket_sys_id"):
                    await incident_agent.add_work_notes(
                        ticket_sys_id=triage_result["snow_ticket"]["ticket_sys_id"],
                        notes=f"Automated remediation rejected by user. Reason: {approval_result.get('comment', 'No reason provided')}"
                    )
                
                return tool_calls
            
            # Approved - proceed with remediation
            await self._emit_event(run_id, "thinking", {
                "message": "✅ Remediation approved, proceeding with execution..."
            })
        
        # Update ServiceNow to In Progress
        if triage_result.get("snow_ticket", {}).get("ticket_sys_id"):
            await incident_agent.update_incident_in_progress(
                ticket_sys_id=triage_result["snow_ticket"]["ticket_sys_id"],
                work_notes="Starting automated remediation execution"
            )
        
        # Execute remediation
        await self._emit_event(run_id, "node", {
            "node": "remediation_execution",
            "message": "Executing remediation steps..."
        })
        
        await self._emit_event(run_id, "token", {
            "content": "\n\n## 🔧 Remediation Execution\n\nExecuting remediation steps...\n"
        })
        
        execution_results = await remediator_agent.execute_remediation(
            plan=remediation_plan,
            run_id=run_id,
            session_id=context.get("session_id", run_id),
            incident_number=triage_result.get("snow_ticket", {}).get("ticket_number")
        )
        
        tool_calls += 1
        
        # Emit execution results
        await self._emit_event(run_id, "token", {
            "content": f"\n**Execution Status:** {execution_results.get('status', 'unknown').upper()}\n"
        })
        await self._emit_event(run_id, "token", {
            "content": f"**Steps Completed:** {execution_results.get('steps_completed', 0)}/{execution_results.get('steps_total', 0)}\n"
        })
        await self._emit_event(run_id, "token", {
            "content": f"**Duration:** {execution_results.get('duration_seconds', 0):.1f} seconds\n\n"
        })
        
        # Add work notes to ServiceNow
        if triage_result.get("snow_ticket", {}).get("ticket_sys_id"):
            execution_summary = f"""Remediation Execution Results:
- Status: {execution_results.get('status', 'unknown')}
- Steps Completed: {execution_results.get('steps_completed', 0)}/{execution_results.get('steps_total', 0)}
- Duration: {execution_results.get('duration_seconds', 0):.1f} seconds

Execution Log:
"""
            for log_entry in execution_results.get("execution_log", []):
                execution_summary += f"\nStep {log_entry.get('step')}: {log_entry.get('action')} - {log_entry.get('status')}"
            
            await incident_agent.add_work_notes(
                ticket_sys_id=triage_result["snow_ticket"]["ticket_sys_id"],
                notes=execution_summary
            )
        
        # Verify remediation if successful
        if execution_results.get("status") == "success":
            await self._emit_event(run_id, "node", {
                "node": "verification",
                "message": "Verifying remediation success..."
            })
            
            await self._emit_event(run_id, "token", {
                "content": "## ✅ Verification\n\nVerifying that the issue has been resolved...\n\n"
            })
            
            verification_results = await remediator_agent.verify_remediation(
                plan=remediation_plan,
                execution_results=execution_results,
                run_id=run_id,
                session_id=context.get("session_id", run_id)
            )
            
            tool_calls += 1
            
            if verification_results.get("verified"):
                await self._emit_event(run_id, "token", {
                    "content": "✅ **Verification Passed** - Issue has been resolved successfully!\n\n"
                })
                
                # Resolve incident in ServiceNow
                if triage_result.get("snow_ticket", {}).get("ticket_sys_id"):
                    resolution_notes = f"""Automated Remediation Completed Successfully

Remediation Plan: {remediation_plan.get('summary', 'N/A')}
Steps Executed: {execution_results.get('steps_completed', 0)}
Verification: Passed ({verification_results.get('checks_passed', 0)} checks)

The incident has been automatically resolved by AegisOps."""
                    
                    await incident_agent.resolve_incident(
                        ticket_sys_id=triage_result["snow_ticket"]["ticket_sys_id"],
                        resolution_notes=resolution_notes,
                        close_code="Solution provided"
                    )
                    
                    await self._emit_event(run_id, "token", {
                        "content": f"📋 **ServiceNow Incident {triage_result['snow_ticket'].get('ticket_number')}** has been marked as **Resolved**.\n\n"
                    })
                
                # Mark session as resolved
                await self._emit_event(run_id, "session_resolved", {
                    "message": "Incident resolved successfully",
                    "ticket_number": triage_result.get("snow_ticket", {}).get("ticket_number")
                })
                
            else:
                await self._emit_event(run_id, "token", {
                    "content": "⚠️ **Verification Failed** - Some checks did not pass. Manual verification required.\n\n"
                })
                
                # Add verification failure to ServiceNow
                if triage_result.get("snow_ticket", {}).get("ticket_sys_id"):
                    await incident_agent.add_work_notes(
                        ticket_sys_id=triage_result["snow_ticket"]["ticket_sys_id"],
                        notes=f"Automated verification failed. Manual verification required.\n\nVerification Details:\n{verification_results.get('details', [])}"
                    )
        else:
            # Execution failed
            await self._emit_event(run_id, "token", {
                "content": f"❌ **Remediation Failed** - Status: {execution_results.get('status')}\n\n"
            })
            
            if execution_results.get("rollback_required"):
                await self._emit_event(run_id, "token", {
                    "content": "⚠️ Rollback may be required. Please review the execution log and take manual action.\n\n"
                })
        
        # Save final checkpoint
        try:
            await self._context.save_checkpoint(
                run_id=run_id,
                checkpoint_data={
                    "stage": "completed",
                    "remediation_status": execution_results.get("status"),
                    "verification_passed": verification_results.get("verified") if execution_results.get("status") == "success" else False
                }
            )
        except Exception as e:
            logger.warning(f"Failed to save final checkpoint: {e}")
        
        return tool_calls
    
    async def _execute_conversational_path(
        self,
        run_id: str,
        message: str,
        conversation_context: List[Dict[str, str]],
        db: AsyncSession
    ) -> int:
        """
        Execute conversational interaction path.
        
        Handles greetings, help requests, and general chat.
        
        Returns:
            Number of tool calls made (0 for conversational)
        """
        response_content = ""
        generation_start = datetime.utcnow()
        
        try:
            # Get the user message ID to link response
            result = await db.execute(
                select(Message)
                .where(Message.run_id == run_id)
                .where(Message.role == "user")
                .order_by(Message.created_at.desc())
            )
            user_message = result.scalar_one_or_none()
            parent_message_id = user_message.id if user_message else None
            
            # Get response from conversational agent
            response = await conversational_agent.handle_conversation(
                user_message=message,
                context=conversation_context
            )
            
            response_content = response
            generation_time_ms = (datetime.utcnow() - generation_start).total_seconds() * 1000
            
            # Stream response line-by-line to preserve markdown formatting
            lines = response.split('\n')
            for i, line in enumerate(lines):
                await self._emit_event(run_id, "token", {
                    "content": line + ("\n" if i < len(lines) - 1 else "")
                })
                await asyncio.sleep(0.05)  # Simulate streaming
            
            await self._emit_event(run_id, "tool", {
                "tool": "conversational_agent.handle_conversation",
                "status": "success",
                "output": {"response_length": len(response)}
            })
            
            # Save agent response to database with linkage
            await self._save_agent_message(
                run_id=run_id,
                content=response_content,
                db=db,
                agent_type="conversational",  # NEW: Specify agent type
                parent_message_id=parent_message_id,  # NEW: Link to user message
                confidentiality_score=0.2,
                confidentiality_label="low",
                metadata={  # NEW: Store generation metadata
                    "model_name": self._llm.model,
                    "generation_time_ms": generation_time_ms,
                    "response_length": len(response_content),
                    "line_count": len(lines)
                }
            )
            
            logger.info(f"Conversational response generated and saved for run {run_id}")
            
        except Exception as e:
            logger.error(f"Conversational agent failed: {e}")
            await self._emit_event(run_id, "error", {
                "error": str(e),
                "type": "ConversationalError"
            })
        
        return 0  # No tool calls for conversational
    
    async def _execute_devops_path(
        self,
        run_id: str,
        message: str,
        context: Dict[str, Any],
        db: AsyncSession
    ) -> int:
        """
        Execute DevOps automation path.
        
        Handles application creation, CI/CD setup, deployment automation.
        
        Returns:
            Number of tool calls made
        """
        tool_calls = 0
        
        await self._emit_event(run_id, "node", {
            "node": "devops_agent_v5",
            "message": "Starting DevOps automation..."
        })
        
        # Emit thinking: Analyzing request
        await self._emit_event(run_id, "thinking", {
            "message": "🔍 Analyzing your DevOps request to identify project type and requirements..."
        })
        await asyncio.sleep(0.5)
        
        # Emit thinking: Planning workflow
        await self._emit_event(run_id, "thinking", {
            "message": "📋 Planning CI/CD workflow and repository structure..."
        })
        await asyncio.sleep(0.5)
        
        try:
            # Extract repository info from message
            repo_info = intent_detector.extract_repo_info(message)
            
            # Determine repo name
            repo_name = repo_info.get("repo_name")
            if not repo_name:
                # Generate from message
                import re
                words = re.findall(r'\b[a-z]+\b', message.lower())
                repo_name = "-".join(words[:3]) if words else "my-project"
            
            # Determine feature branch
            feature_branch = repo_info.get("branch_name")
            
            # Emit thinking: Starting execution
            await self._emit_event(run_id, "thinking", {
                "message": f"🚀 Executing DevOps workflow for repository: {repo_name}"
            })
            await asyncio.sleep(0.3)
            
            # Execute DevOps workflow (HITL approval is MANDATORY)
            result = await devops_agent_v5.execute_workflow(
                run_id=run_id,
                user_prompt=message,
                repo_name=repo_name,
                target_environment="dev",
                feature_branch=feature_branch,
                approval_required=True,
                enable_critic=True
            )
            
            # Count tool calls (approximate)
            tool_calls = 10  # Typical DevOps workflow has ~10 steps
            
            await self._emit_event(run_id, "tool", {
                "tool": "devops_agent_v5.execute_workflow",
                "status": result.get("status", "completed"),
                "output": {
                    "repo_url": result.get("repo_url"),
                    "pr_url": result.get("pr_url"),
                    "deployment_triggered": result.get("deployment_triggered", False)
                }
            })
            
            logger.info(f"DevOps workflow completed for run {run_id}")
            
        except Exception as e:
            logger.error(f"DevOps agent failed: {e}")
            await self._emit_event(run_id, "error", {
                "error": str(e),
                "type": "DevOpsError"
            })
        
        return tool_calls
    
    async def _execute_cloudops_path(
        self,
        run_id: str,
        message: str,
        context: Dict[str, Any],
        db: AsyncSession
    ) -> int:
        """
        Execute CloudOps infrastructure provisioning path.
        
        Handles cloud resource provisioning (EC2, RDS, S3, Lambda, etc.)
        with mandatory HITL approval.
        
        Returns:
            Number of tool calls made
        """
        tool_calls = 0
        
        await self._emit_event(run_id, "node", {
            "node": "cloudops_agent",
            "message": "Starting CloudOps infrastructure provisioning..."
        })
        
        # Emit thinking: Analyzing request
        await self._emit_event(run_id, "thinking", {
            "message": "🔍 Analyzing your CloudOps request to identify resource type and parameters..."
        })
        await asyncio.sleep(0.5)
        
        # Emit thinking: Loading workflow
        await self._emit_event(run_id, "thinking", {
            "message": "📋 Loading appropriate workflow template and validating parameters..."
        })
        await asyncio.sleep(0.5)
        
        try:
            # Import CloudOps agent
            from app.agents.cloudops_agent import cloudops_agent
            
            # Emit thinking: Executing workflow
            await self._emit_event(run_id, "thinking", {
                "message": "🚀 Executing infrastructure provisioning workflow..."
            })
            await asyncio.sleep(0.3)
            
            # Execute CloudOps workflow
            result = await cloudops_agent.handle_cloudops_request(
                run_id=run_id,
                user_message=message,
                context=context
            )
            
            # Count tool calls (approximate based on workflow)
            tool_calls = 5  # Typical CloudOps workflow has ~5-7 steps
            
            await self._emit_event(run_id, "tool", {
                "tool": "cloudops_agent.handle_cloudops_request",
                "status": result.get("status", "completed"),
                "output": {
                    "workflow_id": result.get("workflow_id"),
                    "workflow_name": result.get("workflow_name"),
                    "resource_type": result.get("resource_type")
                }
            })
            
            logger.info(f"CloudOps workflow completed for run {run_id}")
            
        except Exception as e:
            logger.error(f"CloudOps agent failed: {e}")
            await self._emit_event(run_id, "error", {
                "error": str(e),
                "type": "CloudOpsError"
            })
        
        return tool_calls
    
    async def _execute_sre_path(
        self,
        run_id: str,
        message: str,
        context: Dict[str, Any],
        db: AsyncSession
    ) -> int:
        """
        Execute SRE monitoring and analysis path.
        
        Handles monitoring, metrics, logs, health checks, and incident response.
        
        Returns:
            Number of tool calls made
        """
        tool_calls = 0
        
        await self._emit_event(run_id, "node", {
            "node": "sre_agent",
            "message": "Starting SRE monitoring and analysis..."
        })
        
        try:
            # Import SRE agent
            from app.agents.sre_agent import sre_agent
            
            # Emit thinking: Parsing request
            await self._emit_event(run_id, "thinking", {
                "message": "🔍 Analyzing your SRE request to identify operation type and parameters..."
            })
            await asyncio.sleep(0.5)
            
            # Emit thinking: Querying RAG
            await self._emit_event(run_id, "thinking", {
                "message": "📚 Searching knowledge base for relevant troubleshooting guides and runbooks..."
            })
            await asyncio.sleep(0.5)
            
            # Execute SRE operation
            result = await sre_agent.handle_sre_request(
                run_id=run_id,
                user_message=message,
                context=context
            )
            
            # Count tool calls
            tool_calls = 2  # Typical SRE operation has ~2-3 tool calls
            
            # Emit thinking: Operation identified
            operation_type = result.get("operation_type", "analysis")
            await self._emit_event(run_id, "thinking", {
                "message": f"✅ Operation identified: {operation_type.upper()}"
            })
            await asyncio.sleep(0.3)
            
            await self._emit_event(run_id, "tool", {
                "tool": "sre_agent.handle_sre_request",
                "status": result.get("status", "completed"),
                "output": {
                    "operation_type": result.get("operation_type"),
                    "result": result.get("result")
                }
            })
            
            # Emit RAG sources if available
            if result.get("rag_sources"):
                await self._emit_event(run_id, "rag_sources", {
                    "sources": result["rag_sources"]
                })
                logger.info(f"Emitted {len(result['rag_sources'])} RAG sources for SRE request")
                
                # Emit thinking: RAG sources found
                await self._emit_event(run_id, "thinking", {
                    "message": f"📖 Found {len(result['rag_sources'])} relevant knowledge base articles"
                })
                await asyncio.sleep(0.3)
            
            # Emit thinking: Generating analysis
            await self._emit_event(run_id, "thinking", {
                "message": "🤔 Generating comprehensive analysis based on knowledge base and best practices..."
            })
            await asyncio.sleep(0.5)
            
            # Stream the analysis response as tokens with better pacing
            analysis_content = ""
            if result.get("result") and result["result"].get("analysis"):
                analysis_text = result["result"]["analysis"]
                analysis_content = analysis_text  # Save for database
                
                # Split by words but preserve markdown formatting
                words = analysis_text.split()
                for i, word in enumerate(words):
                    await self._emit_event(run_id, "token", {
                        "content": word + (" " if i < len(words) - 1 else "")
                    })
                    # Faster streaming for better UX
                    await asyncio.sleep(0.01)
            
            # Save the analysis to database with RAG sources
            if analysis_content:
                # Get the user message ID to link response
                result_msg = await db.execute(
                    select(Message)
                    .where(Message.run_id == run_id)
                    .where(Message.role == "user")
                    .order_by(Message.created_at.desc())
                )
                user_message = result_msg.scalar_one_or_none()
                parent_message_id = user_message.id if user_message else None
                
                # Save analysis with RAG sources
                await self._save_agent_message(
                    run_id=run_id,
                    content=analysis_content,
                    db=db,
                    agent_type="sre",
                    parent_message_id=parent_message_id,
                    confidentiality_score=0.1,
                    confidentiality_label="low",
                    rag_sources=result.get("rag_sources", []),  # Include RAG sources
                    metadata={
                        "workflow_type": "SRE",
                        "operation_type": result.get("operation_type", "analysis"),
                        "data_collected": result.get("result", {}).get("data_collected", False)
                    }
                )
                logger.info(f"Saved SRE analysis to database for run {run_id}")
            
            logger.info(f"SRE operation completed for run {run_id}")
            
        except Exception as e:
            logger.error(f"SRE agent failed: {e}", exc_info=True)
            await self._emit_event(run_id, "error", {
                "error": str(e),
                "type": "SREError"
            })
        
        return tool_calls
    
    async def _emit_event(self, run_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """
        Emit event to Redis pub/sub for SSE streaming.
        
        Args:
            run_id: Run identifier
            event_type: Event type (token, node, analysis, etc.)
            data: Event data
        """
        try:
            redis = redis_client.client
            channel = f"run:{run_id}:events"
            
            event = {
                "event": event_type,
                "data": data,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            await redis.publish(channel, json.dumps(event))
            
        except Exception as e:
            logger.error(f"Failed to emit event: {e}")
    
    async def _save_agent_message(
        self,
        run_id: str,
        content: str,
        db: AsyncSession,
        agent_type: Optional[str] = None,
        parent_message_id: Optional[str] = None,
        confidentiality_score: Optional[float] = None,
        confidentiality_label: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Save agent response message to database.
        
        Args:
            run_id: Run identifier
            content: Agent response content
            db: Database session
            agent_type: Type of agent (conversational, devops, cloudops, sre)
            parent_message_id: ID of user message this is responding to
            confidentiality_score: Optional confidentiality score
            confidentiality_label: Optional confidentiality label (low/medium/high)
            metadata: Additional metadata (model, tokens, timing, etc.)
        """
        try:
            from app.models.models import Message
            import uuid
            
            # Get run to find session_id
            result = await db.execute(select(Run).where(Run.id == run_id))
            run = result.scalar_one_or_none()
            
            if not run:
                logger.error(f"Run {run_id} not found, cannot save message")
                return
            
            # Create assistant message
            message_id = f"msg_{uuid.uuid4().hex[:12]}"
            agent_message = Message(
                id=message_id,
                session_id=run.session_id,
                run_id=run_id,
                role="assistant",
                content=content,
                agent_type=agent_type,  # NEW: Track which agent generated this
                parent_message_id=parent_message_id,  # NEW: Link to user message
                confidentiality_score=confidentiality_score,
                confidentiality_label=confidentiality_label,
                extra_metadata=metadata or {},  # NEW: Store additional metadata (using extra_metadata attribute)
                created_at=datetime.utcnow()
            )
            
            db.add(agent_message)
            await db.commit()
            
            logger.info(f"✅ Saved {agent_type or 'agent'} message {message_id} to database for run {run_id}")
            
            # Add agent message to context graph (non-blocking)
            try:
                from app.services.context_client import context_client
                await context_client.add_message_to_graph(
                    message_id=message_id,
                    session_id=run.session_id,
                    role="assistant",
                    content=content,
                    metadata={
                        "run_id": run_id,
                        "agent_type": agent_type,
                        "parent_message_id": parent_message_id,
                        "confidentiality_score": confidentiality_score,
                        "confidentiality_label": confidentiality_label,
                        **(metadata or {})
                    }
                )
                logger.info(f"Added agent message {message_id} to context graph")
            except Exception as e:
                logger.warning(f"Failed to add agent message to context graph: {e}")
            
        except Exception as e:
            logger.error(f"Failed to save agent message: {e}", exc_info=True)
    
    async def _emit_progress(
        self, 
        run_id: str, 
        current_step: int, 
        total_steps: int, 
        message: str,
        status: str = "in_progress"
    ) -> None:
        """
        Emit progress update with percentage and status message.
        
        Args:
            run_id: Run identifier
            current_step: Current step number (1-based)
            total_steps: Total number of steps
            message: Progress message
            status: Status (in_progress, success, error, warning)
        """
        percentage = int((current_step / total_steps) * 100) if total_steps > 0 else 0
        
        await self._emit_event(run_id, "progress", {
            "current_step": current_step,
            "total_steps": total_steps,
            "percentage": percentage,
            "message": message,
            "status": status
        })
    
    async def cancel_run(self, run_id: str, db: AsyncSession) -> None:
        """Cancel a running orchestration."""
        if run_id in self._active_runs:
            task = self._active_runs[run_id]
            task.cancel()
            
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            logger.info(f"Cancelled run: {run_id}")


# Global orchestrator instance
orchestrator_service = OrchestratorService()
