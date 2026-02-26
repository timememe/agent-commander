"""Tool definitions and executors for ProxyAPI tool calling."""

from .definitions import TOOL_DEFINITIONS, execute_tool
from .email import EMAIL_TOOL_DEFINITIONS, execute_email_tool

__all__ = [
    "EMAIL_TOOL_DEFINITIONS",
    "TOOL_DEFINITIONS",
    "execute_email_tool",
    "execute_tool",
]
