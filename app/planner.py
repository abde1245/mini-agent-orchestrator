import re

from app.config import (
    ORDER_ID_PATTERN,
    EMAIL_PATTERN,
    CANCEL_INTENT_KEYWORDS,
    EMAIL_INTENT_KEYWORDS,
)
from app.models import TaskStep


class PlanningError(Exception):
    """Raised when the planner cannot produce a valid plan from the input."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class MockLLMPlanner:
    """Deterministic planner that mimics an LLM's function-calling output.

    Instead of calling a remote model, this class uses regex extraction
    and keyword matching to convert natural language into a structured
    task list.  The output format mirrors what you would get back from
    an OpenAI function-calling response, keeping the architecture
    identical to a real LLM integration — swap this class for a real
    API client and everything else stays the same.
    """

    def parse(self, request_text: str) -> list[TaskStep]:
        """Turn a natural language request into an ordered list of tasks.

        Raises PlanningError when the input is too ambiguous or is
        missing critical information needed to build any actionable plan.
        """
        lowered = request_text.lower()

        has_cancel_intent = any(
            kw in lowered for kw in CANCEL_INTENT_KEYWORDS
        )
        has_email_intent = any(
            kw in lowered for kw in EMAIL_INTENT_KEYWORDS
        )

        if not has_cancel_intent and not has_email_intent:
            raise PlanningError(
                "Could not identify any actionable intent in the request. "
                "Supported actions: cancel an order, send a confirmation email."
            )

        order_ids = re.findall(ORDER_ID_PATTERN, request_text)
        emails = re.findall(EMAIL_PATTERN, request_text)

        steps: list[TaskStep] = []
        step_counter = 1

        if has_cancel_intent:
            if not order_ids:
                raise PlanningError(
                    "Cancel intent detected but no order ID found. "
                    "Please include the order number (e.g., #9921)."
                )
            for oid in order_ids:
                steps.append(TaskStep(
                    step=step_counter,
                    tool="cancel_order",
                    parameters={"order_id": oid},
                ))
                step_counter += 1

        if has_email_intent:
            if not emails:
                raise PlanningError(
                    "Email intent detected but no email address found. "
                    "Please include a valid email address."
                )
            for addr in emails:
                message = self._build_email_body(order_ids, addr)
                steps.append(TaskStep(
                    step=step_counter,
                    tool="send_email",
                    parameters={"email": addr, "message": message},
                ))
                step_counter += 1

        return steps

    @staticmethod
    def _build_email_body(order_ids: list[str], email: str) -> str:
        """Compose a human-readable confirmation message."""
        if order_ids:
            ids_str = ", ".join(f"#{oid}" for oid in order_ids)
            return (
                f"Hi, this is a confirmation that your request regarding "
                f"order(s) {ids_str} has been processed. "
                f"A detailed summary has been sent to {email}."
            )
        return (
            f"Hi, your request has been processed. "
            f"A confirmation has been sent to {email}."
        )
