"""
VM Console Streamer

Enhanced streaming service for VM Console with formatting support (emojis, tables, boxes).
"""

import logging
import asyncio
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum

from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """VM Console message types."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    COMMAND = "command"
    OUTPUT = "output"
    APPROVAL = "approval"
    TABLE = "table"
    BOX = "box"


class VMConsoleStreamer:
    """
    Enhanced VM Console streaming with formatting.
    
    Features:
    - Real-time streaming to VM Console
    - Formatted messages (emojis, colors, tables, boxes)
    - HITL approval prompts in VM Console
    - Progress indicators
    - Command execution tracking
    """
    
    def __init__(self):
        self.redis = redis_client
    
    def _get_channel(self, run_id: str) -> str:
        """Get Redis channel for run."""
        return f"vm:{run_id}:events"
    
    async def stream_message(
        self,
        run_id: str,
        message: str,
        message_type: MessageType = MessageType.INFO,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Stream a formatted message to VM Console.
        
        Args:
            run_id: Run ID
            message: Message text
            message_type: Message type (info, success, warning, error)
            metadata: Additional metadata
        """
        channel = self._get_channel(run_id)
        
        # Add emoji based on type
        emoji_map = {
            MessageType.INFO: "ℹ️",
            MessageType.SUCCESS: "✅",
            MessageType.WARNING: "⚠️",
            MessageType.ERROR: "❌",
            MessageType.COMMAND: "🔧",
            MessageType.OUTPUT: "📄",
            MessageType.APPROVAL: "🔐",
            MessageType.TABLE: "📊",
            MessageType.BOX: "📦"
        }
        
        emoji = emoji_map.get(message_type, "")
        formatted_message = f"{emoji} {message}" if emoji else message
        
        event = {
            "event": "vm_output",
            "data": {
                "output": formatted_message,
                "stream": "stdout",
                "type": message_type.value,
                "timestamp": datetime.utcnow().isoformat(),
                **(metadata or {})
            }
        }
        
        try:
            await self.redis.client.publish(channel, json.dumps(event))
            logger.debug(f"Streamed message to {channel}: {message[:50]}...")
        except Exception as e:
            logger.error(f"Failed to stream message: {e}")
    
    async def stream_command(
        self,
        run_id: str,
        command: str,
        description: Optional[str] = None
    ):
        """Stream command execution."""
        message = f"Executing: {command}"
        if description:
            message = f"{description}\n$ {command}"
        
        await self.stream_message(
            run_id=run_id,
            message=message,
            message_type=MessageType.COMMAND
        )
    
    async def stream_success(
        self,
        run_id: str,
        message: str
    ):
        """Stream success message."""
        await self.stream_message(
            run_id=run_id,
            message=message,
            message_type=MessageType.SUCCESS
        )
    
    async def stream_error(
        self,
        run_id: str,
        message: str,
        error: Optional[Exception] = None
    ):
        """Stream error message."""
        full_message = message
        if error:
            full_message = f"{message}\nError: {str(error)}"
        
        await self.stream_message(
            run_id=run_id,
            message=full_message,
            message_type=MessageType.ERROR
        )
    
    async def stream_warning(
        self,
        run_id: str,
        message: str
    ):
        """Stream warning message."""
        await self.stream_message(
            run_id=run_id,
            message=message,
            message_type=MessageType.WARNING
        )
    
    async def stream_table(
        self,
        run_id: str,
        title: str,
        headers: List[str],
        rows: List[List[str]]
    ):
        """
        Stream formatted table to VM Console.
        
        Args:
            run_id: Run ID
            title: Table title
            headers: Column headers
            rows: Table rows
        """
        # Calculate column widths
        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))
        
        # Build table
        separator = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
        
        table_lines = [
            f"\n{title}",
            separator,
            "| " + " | ".join(h.ljust(w) for h, w in zip(headers, col_widths)) + " |",
            separator
        ]
        
        for row in rows:
            table_lines.append(
                "| " + " | ".join(str(cell).ljust(w) for cell, w in zip(row, col_widths)) + " |"
            )
        
        table_lines.append(separator)
        
        table_text = "\n".join(table_lines)
        
        await self.stream_message(
            run_id=run_id,
            message=table_text,
            message_type=MessageType.TABLE
        )
    
    async def stream_box(
        self,
        run_id: str,
        title: str,
        content: str,
        box_type: str = "info"
    ):
        """
        Stream formatted box to VM Console.
        
        Args:
            run_id: Run ID
            title: Box title
            content: Box content
            box_type: Box type (info, success, warning, error)
        """
        # Box characters
        top_left = "╔"
        top_right = "╗"
        bottom_left = "╚"
        bottom_right = "╝"
        horizontal = "═"
        vertical = "║"
        
        # Calculate width
        lines = content.split('\n')
        max_width = max(len(title), max(len(line) for line in lines))
        width = max_width + 4
        
        # Build box
        box_lines = [
            f"\n{top_left}{horizontal * width}{top_right}",
            f"{vertical} {title.center(width - 2)} {vertical}",
            f"{vertical}{horizontal * width}{vertical}"
        ]
        
        for line in lines:
            box_lines.append(f"{vertical} {line.ljust(width - 2)} {vertical}")
        
        box_lines.append(f"{bottom_left}{horizontal * width}{bottom_right}\n")
        
        box_text = "\n".join(box_lines)
        
        # Map box type to message type
        type_map = {
            "info": MessageType.INFO,
            "success": MessageType.SUCCESS,
            "warning": MessageType.WARNING,
            "error": MessageType.ERROR
        }
        
        await self.stream_message(
            run_id=run_id,
            message=box_text,
            message_type=type_map.get(box_type, MessageType.BOX)
        )
    
    async def stream_progress(
        self,
        run_id: str,
        step: str,
        current: int,
        total: int
    ):
        """Stream progress indicator."""
        percentage = int((current / total) * 100) if total > 0 else 0
        bar_length = 30
        filled = int((current / total) * bar_length) if total > 0 else 0
        bar = "█" * filled + "░" * (bar_length - filled)
        
        message = f"{step}: [{bar}] {percentage}% ({current}/{total})"
        
        await self.stream_message(
            run_id=run_id,
            message=message,
            message_type=MessageType.INFO
        )
    
    async def request_approval(
        self,
        run_id: str,
        message: str,
        command: Optional[str] = None,
        timeout: int = 1800  # 30 minutes
    ) -> Dict[str, Any]:
        """
        Request approval in VM Console.
        
        Args:
            run_id: Run ID
            message: Approval message
            command: Optional command to display
            timeout: Timeout in seconds
            
        Returns:
            Dict with approval_id
        """
        import uuid
        approval_id = str(uuid.uuid4())
        
        channel = self._get_channel(run_id)
        
        event = {
            "event": "vm_prompt",
            "data": {
                "type": "approval",
                "message": message,
                "command": command,
                "approval_id": approval_id,
                "timeout": timeout,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
        
        try:
            await self.redis.client.publish(channel, json.dumps(event))
            logger.info(f"Approval request sent: {approval_id}")
            
            return {
                "approval_id": approval_id,
                "timeout": timeout
            }
        except Exception as e:
            logger.error(f"Failed to request approval: {e}")
            raise
    
    async def stream_file_preview(
        self,
        run_id: str,
        file_path: str,
        content: str,
        max_lines: int = 30
    ):
        """Stream file preview to VM Console."""
        lines = content.split('\n')
        preview_lines = lines[:max_lines]
        
        message = f"\n📄 File: {file_path}\n"
        message += "─" * 80 + "\n"
        message += "\n".join(preview_lines)
        
        if len(lines) > max_lines:
            message += f"\n\n... ({len(lines) - max_lines} more lines)"
        
        message += "\n" + "─" * 80
        
        await self.stream_message(
            run_id=run_id,
            message=message,
            message_type=MessageType.OUTPUT
        )
    
    async def stream_workflow_step(
        self,
        run_id: str,
        step_name: str,
        status: str,
        details: Optional[str] = None
    ):
        """Stream workflow step status."""
        status_emoji = {
            "started": "▶️",
            "running": "⏳",
            "completed": "✅",
            "failed": "❌",
            "skipped": "⏭️"
        }
        
        emoji = status_emoji.get(status, "")
        message = f"{emoji} {step_name}: {status.upper()}"
        
        if details:
            message += f"\n  {details}"
        
        message_type = MessageType.SUCCESS if status == "completed" else MessageType.INFO
        if status == "failed":
            message_type = MessageType.ERROR
        
        await self.stream_message(
            run_id=run_id,
            message=message,
            message_type=message_type
        )


# Global instance
vm_console_streamer = VMConsoleStreamer()
