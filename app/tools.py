import asyncio
import random
from typing import Any, Callable, Awaitable

from app.config import CANCEL_FAILURE_RATE, EMAIL_DELAY_SECONDS


class ToolExecutionError(Exception):
    """Raised when a tool encounters an internal error during execution."""

    def __init__(self, tool_name: str, reason: str) -> None:
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"Tool '{tool_name}' failed: {reason}")


async def cancel_order(order_id: str, force_fail: bool = False) -> dict[str, Any]:
    """Attempt to cancel the given order.

    Simulates a real cancellation service with a 20% random failure rate.
    The randomness models real-world transient failures so the orchestrator
    can demonstrate its guardrail logic.  When force_fail is True, failure
    is guaranteed (used by the visualizer's "Simulate Failure" button).
    """
    await asyncio.sleep(0.1)

    if force_fail or random.random() < CANCEL_FAILURE_RATE:
        return {
            "success": False,
            "order_id": order_id,
            "message": f"Cancellation failed for order #{order_id}. "
                       f"The order may already be shipped or locked.",
        }

    return {
        "success": True,
        "order_id": order_id,
        "message": f"Order #{order_id} has been successfully cancelled.",
    }


async def send_email(email: str, message: str) -> dict[str, Any]:
    """Send a confirmation email to the given address.

    Simulates network latency with a 1-second delay before returning
    a confirmation payload.
    """
    await asyncio.sleep(EMAIL_DELAY_SECONDS)

    return {
        "sent": True,
        "email": email,
        "message": message,
    }


ToolFunction = Callable[..., Awaitable[dict[str, Any]]]


class ToolRegistry:
    """Central registry that maps tool names to their async implementations.

    Every tool the orchestrator can call must be registered here first.
    This keeps tool resolution in one place and makes the system easy
    to extend with new capabilities.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolFunction] = {}

    def register(self, name: str, fn: ToolFunction) -> None:
        """Register a tool function under the given name."""
        self._tools[name] = fn

    def get(self, name: str) -> ToolFunction:
        """Look up a tool by name. Raises KeyError if not found."""
        if name not in self._tools:
            raise KeyError(f"Unknown tool: '{name}'")
        return self._tools[name]

    def available_tools(self) -> list[str]:
        """Return the list of all registered tool names."""
        return list(self._tools.keys())


def build_default_registry() -> ToolRegistry:
    """Wire up the standard set of tools and return a ready-to-use registry."""
    registry = ToolRegistry()
    registry.register("cancel_order", cancel_order)
    registry.register("send_email", send_email)
    return registry
