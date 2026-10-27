# CodeForge AI - Local Development Guide

This guide describes how to run the CodeForge AI FastAPI backend and background task worker locally.

---

## Architecture Overview

CodeForge AI uses a decoupled, reliable queue architecture:
- **API Server** (`FastAPI`): Receives `POST /tasks`, validates GitHub repositories, stores tasks with `status="queued"` in PostgreSQL, and returns the task ID immediately without holding HTTP connections open.
- **Job Queue**: Backed by PostgreSQL (`tasks` table) using `SELECT ... FOR UPDATE SKIP LOCKED` for reliable, crash-resilient queueing.
- **Worker Process** (`TaskWorker`): Claims queued tasks, executes the LangGraph autonomous software engineering agent, enforces execution timeouts, captures test metrics, records unified git diffs, and recovers stale running tasks after crashes.

---

## Prerequisites

1. **Python 3.11+** installed.
2. **PostgreSQL** running locally (e.g. `localhost:5432/codeforge_ai`).
3. **Git** installed on host.
4. **Docker** or **Podman** (optional; required if executing untrusted repository test suites inside disposable isolated containers).

---

## Configuration (`backend/.env`)

Ensure `backend/.env` is configured with your database and provider keys:

```dotenv
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/codeforge_ai
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b
GITHUB_TOKEN=your_github_personal_access_token_here
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Optional: Set to true if you want the API server to run the worker in a background thread
ENABLE_IN_PROCESS_WORKER=false
WORKER_POLL_INTERVAL=1.0
WORKER_STALE_TIMEOUT=300
```

---

## Running Locally

### Option A: Dedicated Worker Process (Recommended)

Run the API server and worker in separate terminal windows:

#### Terminal 1: API Server
```bash
cd backend
.venv\Scripts\activate  # Windows (or source .venv/bin/activate on Linux/macOS)
uvicorn app.main:app --reload --reload-dir app --port 8000
```

#### Terminal 2: Background Task Worker
```bash
cd backend
.venv\Scripts\activate  # Windows (or source .venv/bin/activate on Linux/macOS)
python -m app.worker
```

### Option B: Single-Process In-Memory Worker (Minimal Setup)

Set `ENABLE_IN_PROCESS_WORKER=true` in `backend/.env`:
```dotenv
ENABLE_IN_PROCESS_WORKER=true
```

Then start only the API server:
```bash
cd backend
uvicorn app.main:app --reload --reload-dir app --port 8000
```
The FastAPI lifespan context manager will automatically start the background worker thread on startup and shut it down cleanly on exit.

---

## Testing the Flow

### 1. Create a Task
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "repository_url": "https://github.com/octocat/Hello-World",
    "task_description": "Fix bug in arithmetic calculator.",
    "acceptance_criteria": "All unit tests pass.",
    "issue_number": 42
  }'
```
Returns HTTP 201 immediately with task ID:
```json
{
  "id": 1,
  "repository_url": "https://github.com/octocat/Hello-World",
  "status": "queued",
  "current_agent_stage": "queued",
  "retry_count": 0,
  "max_retries": 3,
  ...
}
```

### 2. Inspect Current Task State
```bash
curl http://localhost:8000/tasks/1/state
```

### 3. Inspect Chronological Event Stream
```bash
curl http://localhost:8000/tasks/1/events
```

### 4. Inspect Applied File Changes and Diffs
```bash
curl http://localhost:8000/tasks/1/changes
```

### 5. Inspect Verification Test Runs
```bash
curl http://localhost:8000/tasks/1/tests
```

### 6. Cancel a Task
```bash
curl -X POST http://localhost:8000/tasks/1/cancel
```

### 7. Retry a Failed Task
```bash
curl -X POST http://localhost:8000/tasks/1/retry
```

---

## Running the Automated Test Suite

Run the full pytest suite (88 tests):
```bash
cd backend
.venv\Scripts\python -m pytest -v
```
