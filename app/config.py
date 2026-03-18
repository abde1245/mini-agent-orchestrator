from enum import Enum


class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    PLANNING = "PLANNING"
    PLANNING_FAILED = "PLANNING_FAILED"
    EXECUTING = "EXECUTING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


CANCEL_FAILURE_RATE = 0.20
EMAIL_DELAY_SECONDS = 1.0
TOOL_TIMEOUT_SECONDS = 10.0

ORDER_ID_PATTERN = r"#(\d+)"
EMAIL_PATTERN = r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"

CANCEL_INTENT_KEYWORDS = ["cancel", "revoke", "void", "stop", "undo"]
EMAIL_INTENT_KEYWORDS = [
    "email", "mail", "send", "notify", "confirmation", "confirm"
]
