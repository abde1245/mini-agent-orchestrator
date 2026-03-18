# Mini Agent Orchestrator

An event-driven order processing agent built with Python and FastAPI. It accepts natural language requests through a single API endpoint, decomposes them into executable tasks, and runs those tasks asynchronously with built-in guardrail enforcement.

## What It Does

A user sends a request like _"Cancel my order #9921 and email me the confirmation at user@example.com"_ and the system:

1. Parses the natural language into a structured plan (which tools to call, in what order, with what parameters).
2. Executes each step asynchronously, tracking per-step status.
3. Enforces guardrails - if order cancellation fails, the confirmation email is never sent.
4. Returns a detailed JSON response showing every step, its outcome, and the overall workflow status.
5. **Live Dashboard Visualizer** - A built-in real-time pipeline visualizer powered by WebSockets.

### Live Dashboard

The application includes a built-in interface for observing workflows in real-time. Visit `http://localhost:8000/` in your browser to access the **Live Workflow Visualizer**. It connects directly to the backend to stream node states as they transition from Pending to Success/Failure.

## Why FastAPI

FastAPI was chosen for three reasons:

- **Native async support.** The entire request lifecycle - planning, tool execution, response serialization - runs on an async event loop without any thread-pool workarounds. `asyncio.wait_for` wraps every tool call with a configurable timeout, and the 1-second email delay genuinely sleeps the coroutine, not the thread.
- **Pydantic integration.** Request validation (`min_length=1` on the input string) and response serialization (enums, nested models, optional fields) are handled declaratively in the schema layer. There is no manual JSON parsing or validation code in the endpoint.
- **Lightweight.** The entire dependency footprint is three packages. No ORMs, no middleware stacks, no framework magic to work around.

## Architecture

```
  POST /process
       │
       ▼
  ┌──────────┐     ┌───────────────┐     ┌──────────────┐
  │  Planner │───▶│  Orchestrator │────▶│ Tool Registry│
  │ (MockLLM)│     │ (Async Engine)│     │              │
  │          │     │               │     │ cancel_order │
  │ NL → Plan│     │ Guards + Exec │     │ send_email   │
  └──────────┘     └───────────────┘     └──────────────┘
```

### State Machine

Every request transitions through a deterministic state machine:

```
PENDING ──▶ PLANNING ──▶ EXECUTING ──▶ SUCCESS
                │              │
                ▼              ▼
          PLANNING_FAILED    FAILED
```

- **PENDING → PLANNING**: The planner receives the raw text and attempts to extract intents, order IDs, and email addresses.
- **PLANNING → PLANNING_FAILED**: If the input is gibberish, missing required fields (no order ID for a cancel intent, no email for an email intent), or contains no recognizable action.
- **PLANNING → EXECUTING**: The planner produced a valid step list. The orchestrator begins sequential tool invocation.
- **EXECUTING → SUCCESS**: Every tool completed without error.
- **EXECUTING → FAILED**: A tool reported failure (e.g., `cancel_order` returned `success: false`), timed out, or raised an exception. All subsequent steps are marked `SKIPPED`.

### How State Is Tracked

There is no external database or message queue. State lives entirely within the request lifecycle:

- A `ProcessResponse` object accumulates `TaskStep` entries as the orchestrator walks through the plan.
- Each `TaskStep` carries its own `StepStatus` (PENDING → SUCCESS / FAILED / SKIPPED), plus the raw result payload from the tool.
- The orchestrator holds no mutable state between requests. Every invocation starts from a clean slate. This keeps the system stateless and horizontally scalable.

### How the Planner Works

The planner is a deterministic mock that structurally mirrors what a real OpenAI function-calling integration would produce. Instead of hitting a remote model, it uses:

- **Keyword matching** against curated intent lists (`cancel`, `revoke`, `void` → cancel intent; `email`, `send`, `confirmation` → email intent).
- **Regex extraction** for order IDs (`#(\d+)`) and email addresses.
- **Structured output** - a list of `TaskStep` objects with tool names and parameter dicts, identical to what the orchestrator would receive from a deserialized function-calling response.

Swapping this for a real OpenAI client means replacing one class. The orchestrator, tool registry, and state machine stay untouched.

### How LLM Unreliability Is Handled

Since the planner is the only component that interprets unstructured input, all ambiguity is resolved here with explicit failure modes:

| Scenario | Planner Behavior |
|---|---|
| No recognizable intent | Raises `PlanningError` with a message listing supported actions |
| Cancel intent but no `#` order ID | Raises `PlanningError` asking for the order number |
| Email intent but no email address | Raises `PlanningError` asking for the address |
| Valid intents with valid parameters | Returns a structured plan |

The orchestrator never sees ambiguous data. If the planner can't produce a clean plan, the request fails at the planning stage with a clear error message - it never enters the execution phase with partial or guessed data.

In a production setup with a real LLM, you would add response schema validation (JSON schema matching against the expected function-call format) and retry logic with exponential backoff. The architecture supports this cleanly because the planner is a standalone component behind a single `.parse()` interface.

### Guardrail Design

Guardrails live at the **orchestrator level**, not inside individual tools. The tools (`cancel_order`, `send_email`) are pure functions - they do their job and report results. They have no knowledge of other tools or the overall workflow.

The orchestrator checks every tool result after execution. For `cancel_order`, it inspects the `success` field. If `false`:

1. The current step is marked `FAILED`.
2. All remaining steps are marked `SKIPPED` (their tool functions are never called).
3. The workflow status becomes `FAILED` with a descriptive error.

This design keeps individual tools simple and testable in isolation, while concentrating control flow decisions in the orchestrator where they belong.

### Async Execution Model

The system is fully async from endpoint to tool:

- The FastAPI endpoint is an `async def` handler.
- `cancel_order` and `send_email` are `async` functions using `asyncio.sleep` (non-blocking).
- Every tool invocation is wrapped in `asyncio.wait_for(tool_fn(...), timeout=TOOL_TIMEOUT_SECONDS)` to prevent any single tool from hanging the request indefinitely.

Tools run sequentially within a request because the plan represents a dependency chain (email depends on cancel's outcome). There is no parallelism _within_ a request, but the async model means the server handles concurrent _requests_ without blocking.

## Project Structure

```
mini-agent-orchestrator/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, POST /process endpoint
│   ├── config.py           # Enums, constants, patterns
│   ├── models.py           # Pydantic request/response schemas
│   ├── planner.py          # Mock LLM planner (NL → task list)
│   ├── tools.py            # Tool implementations + registry
│   └── orchestrator.py     # Async execution engine with guardrails
├── tests/
│   └── test_api.py         # 8 automated test cases
├── requirements.txt
└── README.md
```

## Setup

```bash
cd mini-agent-orchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the Server

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

**Alternative Run Method**:
```bash
python -m app.main
```

## Example Requests

**Happy path - cancel and email:**
```bash
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{"request": "Cancel my order #9921 and email me the confirmation at user@example.com"}'
```

**Edge case - missing email:**
```bash
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{"request": "Cancel order #9921 and send confirmation"}'
```

**Edge case - unrecognizable input:**
```bash
curl -X POST http://localhost:8000/process \
  -H "Content-Type: application/json" \
  -d '{"request": "asdfghjkl"}'
```

## Running Tests

```bash
source .venv/bin/activate
pip install pytest pytest-asyncio httpx
python -m pytest tests/test_api.py -v
```

The test suite covers:

1. Happy path (cancel succeeds → email sent → SUCCESS)
2. Failure path (cancel fails → email skipped → FAILED)
3. Missing order ID → PLANNING_FAILED
4. Missing email address → PLANNING_FAILED
5. Completely malformed input → PLANNING_FAILED
6. Empty request string → 422 validation error
7. Cancel-only request (no email step)
8. Unique request IDs across calls

## Walkthrough Script (2–3 minute video)

**0:00–0:30 - What the system does.**
Open the README or an architecture diagram. Explain the single-endpoint design: NL input → planner → orchestrator → tools → structured response. Mention the state machine and guardrail concept.

**0:30–1:30 - Live API demo.**
Start the server. Run the happy-path curl command, walk through the JSON response showing both steps succeeded. Then force a cancel failure (run the request a few times until the 20% failure triggers, or temporarily set `CANCEL_FAILURE_RATE = 1.0` in config). Show that `send_email` is `SKIPPED` and the status is `FAILED`.

**1:30–2:30 - Deep dive: orchestrator + guardrail logic.**
Open `orchestrator.py`. Walk through the `execute` method: the sequential loop, `asyncio.wait_for` timeout wrapping, the `_is_step_failure` check after each tool, and the `_skip_remaining` call that marks downstream steps. Highlight that tools are stateless and the orchestrator owns all control flow.
