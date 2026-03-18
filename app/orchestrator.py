import asyncio
import logging
from typing import Any, Callable, Awaitable, Optional

from app.config import WorkflowStatus, StepStatus, TOOL_TIMEOUT_SECONDS
from app.models import TaskStep, ProcessResponse
from app.tools import ToolRegistry, ToolExecutionError

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def _noop_callback(data: dict[str, Any]) -> None:
    pass


class Orchestrator:
    """Executes a planned sequence of tool calls with guardrail enforcement.

    The orchestrator walks through each step in order.  After every tool
    invocation it checks the result — if a critical step (like cancel_order)
    reports failure, all subsequent steps are marked SKIPPED and the
    workflow terminates with a FAILED status.  This keeps the guardrail
    logic at the orchestrator level rather than buried inside individual
    tools.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(
        self,
        plan: list[TaskStep],
        request_id: str,
        original_request: str,
        force_fail: bool = False,
        event_cb: Optional[EventCallback] = None,
    ) -> ProcessResponse:
        """Run through the plan step by step, returning a full response."""
        cb = event_cb or _noop_callback
        executed_steps: list[TaskStep] = []
        workflow_error: Optional[str] = None
        final_status = WorkflowStatus.SUCCESS

        for idx, step in enumerate(plan):
            await cb({"event": "step_started", "step": step.step, "tool": step.tool})

            try:
                tool_fn = self._registry.get(step.tool)
            except KeyError as err:
                step.status = StepStatus.FAILED
                step.result = {"error": str(err)}
                executed_steps.append(step)
                final_status = WorkflowStatus.FAILED
                workflow_error = f"Unknown tool '{step.tool}' at step {step.step}."
                await cb({"event": "step_failed", "step": step.step, "tool": step.tool, "error": workflow_error})
                await self._skip_remaining(plan[idx + 1:], executed_steps, cb)
                break

            extra_kwargs: dict[str, Any] = {}
            if step.tool == "cancel_order" and force_fail:
                extra_kwargs["force_fail"] = True

            try:
                result = await asyncio.wait_for(
                    tool_fn(**step.parameters, **extra_kwargs),
                    timeout=TOOL_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                step.status = StepStatus.FAILED
                step.result = {"error": f"Tool '{step.tool}' timed out."}
                executed_steps.append(step)
                final_status = WorkflowStatus.FAILED
                workflow_error = (
                    f"Step {step.step} ({step.tool}) exceeded the "
                    f"{TOOL_TIMEOUT_SECONDS}s timeout."
                )
                await cb({"event": "step_failed", "step": step.step, "tool": step.tool, "error": workflow_error})
                await self._skip_remaining(plan[idx + 1:], executed_steps, cb)
                break
            except ToolExecutionError as err:
                step.status = StepStatus.FAILED
                step.result = {"error": str(err)}
                executed_steps.append(step)
                final_status = WorkflowStatus.FAILED
                workflow_error = (
                    f"Step {step.step} ({step.tool}) raised an error: {err}"
                )
                await cb({"event": "step_failed", "step": step.step, "tool": step.tool, "error": workflow_error})
                await self._skip_remaining(plan[idx + 1:], executed_steps, cb)
                break
            except (TypeError, ValueError) as err:
                step.status = StepStatus.FAILED
                step.result = {"error": f"Invalid parameters: {err}"}
                executed_steps.append(step)
                final_status = WorkflowStatus.FAILED
                workflow_error = (
                    f"Step {step.step} ({step.tool}) received bad parameters: {err}"
                )
                await cb({"event": "step_failed", "step": step.step, "tool": step.tool, "error": workflow_error})
                await self._skip_remaining(plan[idx + 1:], executed_steps, cb)
                break

            if self._is_step_failure(step.tool, result):
                step.status = StepStatus.FAILED
                step.result = result
                executed_steps.append(step)
                final_status = WorkflowStatus.FAILED
                workflow_error = (
                    f"{result.get('message', 'Tool reported failure.')} "
                    f"Downstream tasks were skipped."
                )
                await cb({"event": "step_failed", "step": step.step, "tool": step.tool, "error": result.get("message", "")})
                await self._skip_remaining(plan[idx + 1:], executed_steps, cb)
                break

            step.status = StepStatus.SUCCESS
            step.result = result
            executed_steps.append(step)
            await cb({"event": "step_success", "step": step.step, "tool": step.tool, "result": result})
            logger.info(
                "Step %d (%s) completed successfully.", step.step, step.tool
            )

        return ProcessResponse(
            status=final_status,
            request_id=request_id,
            original_request=original_request,
            steps_executed=executed_steps,
            error=workflow_error,
        )

    @staticmethod
    def _is_step_failure(tool_name: str, result: dict) -> bool:
        """Check whether a tool result should be treated as a failure.

        For cancel_order the result carries an explicit success flag.
        Other tools are assumed successful if they return without raising.
        """
        if tool_name == "cancel_order":
            return not result.get("success", False)
        return False

    @staticmethod
    async def _skip_remaining(
        remaining: list[TaskStep],
        executed: list[TaskStep],
        cb: EventCallback,
    ) -> None:
        """Mark all remaining steps as SKIPPED and append them to the log."""
        for step in remaining:
            step.status = StepStatus.SKIPPED
            step.result = None
            executed.append(step)
            await cb({"event": "step_skipped", "step": step.step, "tool": step.tool})
