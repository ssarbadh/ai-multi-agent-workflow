"""
Intent Detection Service

Detects whether user input is conversational or DevOps-related.
"""

import logging
import re
from typing import Dict, Any, Optional, List
from enum import Enum

from app.services.llm_client import llm_client

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """User intent types."""
    CONVERSATIONAL = "conversational"
    DEVOPS = "devops"
    CLOUDOPS = "cloudops"
    SRE = "sre"
    INCIDENT = "incident"  # Troubleshooting, incident analysis, problem resolution
    UNKNOWN = "unknown"


class IntentDetector:
    """
    Detect user intent using LLM-based semantic understanding.
    
    Conversational: "hi", "hello", "what can you do", "help me understand"
    DevOps: "create app", "build API", "setup repo", "deploy code" (any language)
    """
    
    def __init__(self):
        self.llm = llm_client
    
    async def detect(self, user_input: str, context: Optional[List[Dict]] = None) -> Intent:
        """
        Detect user intent using LLM-first approach for semantic understanding.
        
        Args:
            user_input: User's message
            context: Previous conversation context
            
        Returns:
            Intent enum (CONVERSATIONAL or DEVOPS)
        """
        user_input_lower = user_input.lower().strip()
        
        # Only use pattern matching for obvious conversational greetings
        if self._is_simple_greeting(user_input_lower):
            logger.info(f"Intent detected (greeting pattern): CONVERSATIONAL")
            return Intent.CONVERSATIONAL
        
        # Use LLM for semantic understanding (primary method)
        intent = await self._llm_detect(user_input, context)
        logger.info(f"Intent detected (LLM): {intent}")
        return intent
    
    def _is_simple_greeting(self, user_input: str) -> bool:
        """Check if input is a simple greeting (fast path)."""
        simple_greetings = [
            r"^(hi|hello|hey|greetings)[\s\W]*$",
            r"^(how are you|what's up|wassup)[\s\W]*$",
            r"^(thanks|thank you|thx)[\s\W]*$",
            r"^(bye|goodbye|see you)[\s\W]*$",
        ]
        
        for pattern in simple_greetings:
            if re.match(pattern, user_input, re.IGNORECASE):
                return True
        return False
    
    async def _llm_detect(self, user_input: str, context: Optional[List[Dict]] = None) -> Intent:
        """LLM-based intent detection with semantic understanding."""
        
        # Build context string if available
        context_str = ""
        if context and len(context) > 0:
            context_str = "\n\nPrevious conversation:\n"
            for msg in context[-3:]:  # Last 3 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                context_str += f"{role}: {content}\n"
        
        prompt = f"""You are an intent classifier for AegisOps, a DevOps automation and incident management system.

Classify the user's message into EXACTLY ONE of these categories:

**INCIDENT** - User is reporting an ACTIVE problem that needs immediate troubleshooting:
- Something IS broken, failing, stuck, down, or not working RIGHT NOW
- Operational issues requiring investigation and resolution
- Examples:
  ✓ "Pod is stuck in production"
  ✓ "Service is down"
  ✓ "Database connection failing"
  ✓ "API returning 500 errors"
  ✓ "Server crashed"
  ✓ "Application is unresponsive"

**DEVOPS** - User wants to CREATE/BUILD/DEVELOP code or applications:
- Building applications, writing code, generating programs
- Repository operations, CI/CD setup
- Examples:
  ✓ "Create a palindrome app"
  ✓ "Build a REST API"
  ✓ "Setup a Java project"
  ✓ "Create Dockerfile"
  ✓ "Setup CI/CD pipeline"

**CLOUDOPS** - User wants to PROVISION/MANAGE cloud infrastructure:
- Creating cloud resources (EC2, RDS, S3, Lambda, VPC, etc.)
- Infrastructure-as-Code operations
- Examples:
  ✓ "Create an EC2 instance"
  ✓ "Provision RDS database"
  ✓ "Setup S3 bucket"
  ✓ "Deploy Lambda function"

**SRE** - User wants to MONITOR or CHECK system health/metrics:
- Viewing metrics, logs, traces
- Health checks and monitoring
- Examples:
  ✓ "Show me CPU metrics"
  ✓ "Check server health"
  ✓ "Get logs from pod"
  ✓ "Monitor application performance"

**CONVERSATIONAL** - Everything else:
- General questions about the system
- Asking HOW TO do something (not reporting a problem)
- Greetings and casual chat
- Examples:
  ✓ "What can you do?"
  ✓ "How do I troubleshoot pods?" (asking for guidance, not reporting problem)
  ✓ "Help me understand Kubernetes"
  ✓ "Hello"

CRITICAL DISTINCTION:
- "Pod is stuck" → INCIDENT (reporting active problem)
- "How do I fix a stuck pod?" → CONVERSATIONAL (asking for guidance)
{context_str}

User message: "{user_input}"

Think carefully about what the user is actually asking for. Respond with ONLY ONE WORD: INCIDENT, DEVOPS, CLOUDOPS, SRE, or CONVERSATIONAL"""
        
        try:
            messages = [
                {"role": "system", "content": "You are an intent classifier. Respond with ONLY one word: INCIDENT, DEVOPS, CLOUDOPS, SRE, or CONVERSATIONAL. No explanation."},
                {"role": "user", "content": prompt}
            ]
            response = await self.llm.chat_completion(messages, max_tokens=300, temperature=0.1)
            response_clean = response["content"].strip().upper()
            
            logger.info(f"LLM intent classification: '{user_input[:50]}...' → '{response_clean}' (length: {len(response_clean)})")
            
            # Parse response - be strict about matching
            if "INCIDENT" in response_clean:
                return Intent.INCIDENT
            elif "CLOUDOPS" in response_clean:
                return Intent.CLOUDOPS
            elif "DEVOPS" in response_clean:
                return Intent.DEVOPS
            elif "SRE" in response_clean:
                return Intent.SRE
            elif "CONVERSATIONAL" in response_clean:
                return Intent.CONVERSATIONAL
            else:
                logger.warning(f"LLM returned unexpected response: '{response_clean}' (length: {len(response_clean)}), defaulting to CONVERSATIONAL")
                return Intent.CONVERSATIONAL
                
        except Exception as e:
            logger.error(f"LLM intent detection failed: {e}", exc_info=True)
            # FAIL EXPLICITLY - no fallbacks allowed
            raise ValueError(f"Intent detection failed - LLM unavailable or misconfigured: {e}")
    
    def extract_repo_info(self, user_input: str) -> Dict[str, Optional[str]]:
        """
        Extract repository and branch information from user input.
        
        Returns:
            Dict with 'repo_name' and 'branch_name' (None if not found)
        """
        repo_name = None
        branch_name = None
        
        # Pattern: "repo name is X" or "repository name is X"
        repo_match = re.search(
            r"(?:repo(?:sitory)?\s+(?:name\s+)?is|repo(?:sitory)?:)\s+([a-zA-Z0-9_-]+)",
            user_input,
            re.IGNORECASE
        )
        if repo_match:
            repo_name = repo_match.group(1)
        
        # Pattern: "branch name is X" or "branch: X"
        branch_match = re.search(
            r"(?:branch\s+(?:name\s+)?is|branch:)\s+([a-zA-Z0-9_/-]+)",
            user_input,
            re.IGNORECASE
        )
        if branch_match:
            branch_name = branch_match.group(1)
        
        return {
            "repo_name": repo_name,
            "branch_name": branch_name
        }


# Global instance
intent_detector = IntentDetector()
