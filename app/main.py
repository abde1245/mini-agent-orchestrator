import uuid
import logging
import os
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import WorkflowStatus
from app.models import ProcessRequest, ProcessResponse
from app.planner import MockLLMPlanner, PlanningError
from app.orchestrator import Orchestrator
from app.tools import build_default_registry
from app.events import manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Mini Agent Orchestrator",
    description=(
        "A lightweight, event-driven order processing agent. Accepts "
        "natural language input, plans a task sequence using a mock LLM, "
        "and executes the plan asynchronously with guardrail enforcement."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

planner = MockLLMPlanner()
tool_registry = build_default_registry()
orchestrator = Orchestrator(tool_registry)


@app.get("/", response_class=HTMLResponse)
async def serve_visualizer() -> HTMLResponse:
    """Serve the static visualizer.html for the Live Workflow Dashboard."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    filepath = os.path.join(root_dir, "visualizer.html")
    with open(filepath, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Long-lived WebSocket connection for streaming workflow events."""
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


@app.post("/process", response_model=ProcessResponse)
async def process_request(body: ProcessRequest, request: Request) -> ProcessResponse:
    """Accept a natural language request and execute the resulting plan.

    The endpoint moves through a simple state machine:
    PENDING -> PLANNING -> EXECUTING -> SUCCESS or FAILED.
    Each transition is logged and reflected in the response payload.
    """
    request_id = str(uuid.uuid4())
    force_fail = request.headers.get("x-force-fail", "false").lower() == "true"

    logger.info("[%s] Received request: %s", request_id, body.request)
    await manager.broadcast({
        "event": "workflow_started",
        "request_id": request_id,
    })

    logger.info("[%s] State: PLANNING", request_id)
    await manager.broadcast({
        "event": "planning",
        "request_id": request_id,
    })

    try:
        plan = planner.parse(body.request)
    except PlanningError as err:
        logger.warning("[%s] Planning failed: %s", request_id, err.reason)
        await manager.broadcast({
            "event": "planning_failed",
            "request_id": request_id,
            "error": err.reason,
        })
        await manager.broadcast({
            "event": "workflow_done",
            "request_id": request_id,
            "status": "PLANNING_FAILED",
        })
        return ProcessResponse(
            status=WorkflowStatus.PLANNING_FAILED,
            request_id=request_id,
            original_request=body.request,
            steps_executed=[],
            error=err.reason,
        )

    tasks_payload = [
        {"step": s.step, "tool": s.tool, "parameters": s.parameters}
        for s in plan
    ]
    await manager.broadcast({
        "event": "plan_ready",
        "request_id": request_id,
        "tasks": tasks_payload,
    })

    logger.info(
        "[%s] State: EXECUTING — %d step(s) planned", request_id, len(plan)
    )

    async def event_callback(data: dict[str, Any]) -> None:
        data["request_id"] = request_id
        await manager.broadcast(data)

    response = await orchestrator.execute(
        plan, request_id, body.request,
        force_fail=force_fail,
        event_cb=event_callback,
    )

    await manager.broadcast({
        "event": "workflow_done",
        "request_id": request_id,
        "status": response.status.value,
    })

    logger.info("[%s] State: %s", request_id, response.status.value)
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for anything that slips past normal error handling."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "status": WorkflowStatus.FAILED,
            "request_id": "unknown",
            "original_request": "",
            "steps_executed": [],
            "error": "An unexpected internal error occurred.",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)

