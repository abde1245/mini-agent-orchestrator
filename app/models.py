from typing import Any, Optional
from pydantic import BaseModel, Field

from app.config import WorkflowStatus, StepStatus


class ProcessRequest(BaseModel):
    request: str = Field(
        ...,
        min_length=1,
        description="Natural language instruction for the agent to process."
    )


class TaskStep(BaseModel):
    step: int
    tool: str
    parameters: dict[str, Any]
    status: StepStatus = StepStatus.PENDING
    result: Optional[dict[str, Any]] = None


class ProcessResponse(BaseModel):
    status: WorkflowStatus
    request_id: str
    original_request: str
    steps_executed: list[TaskStep]
    error: Optional[str] = None
