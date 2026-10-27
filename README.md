# CodeForge AI

CodeForge AI is an autonomous AI software-engineering agent that accepts a GitHub repository and a bug report or issue, investigates the codebase, plans and executes code changes, runs tests in an isolated sandbox, verifies results independently, and prepares a ready-to-review GitHub pull request.

CodeForge AI enforces strict safety: **it never merges pull requests automatically** and **strictly requires human approval before pushing or opening a PR**.

---

## Technology Stack

- **Frontend:** React 18, Vite, JavaScript, CSS (vanilla design system with status pulse animations)
- **Backend:** Python 3.10+, FastAPI, Uvicorn
- **AI Agent Workflow:** LangGraph, LangChain
- **LLM Provider:** Groq API (`openai/gpt-oss-120b`)
- **GitHub Integration:** PyGithub / GitHub REST API, Git CLI
- **Database & Migrations:** PostgreSQL, SQLAlchemy 2.x, Alembic
- **Testing:** pytest (backend, 123 tests), Node test runner (frontend, 12 tests)

---

## Prerequisites

Before starting, ensure the following software is installed on your host system:

1. **Python 3.10+** (with `pip` and virtual environment support)
2. **Node.js 18+** & **npm**
3. **Git CLI** (installed and available on system `PATH`)
4. **PostgreSQL 14+** (running on `localhost:5432`)
5. **Docker** or **Podman** (optional for container sandbox; if unavailable, host test execution of untrusted repository code is safely refused with exit code `126`)

---

## Environment Configuration

### 1. Backend (`backend/.env`)

Copy `backend/.env.example` to `backend/.env`:

```env
# Database Configuration (PostgreSQL)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/codeforge_ai

# Groq LLM Configuration
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile

# GitHub Integration
GITHUB_TOKEN=your_github_personal_access_token_here

# CORS Configuration (comma-separated origins)
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Background Worker Settings
ENABLE_IN_PROCESS_WORKER=false
WORKER_POLL_INTERVAL=1.0
WORKER_STALE_TIMEOUT=300
```

#### GitHub Token Configuration
- Generate a Personal Access Token (classic or fine-grained) at [github.com/settings/tokens](https://github.com/settings/tokens).
- For private repositories or PR creation, grant the `repo` scope.
- Set `GITHUB_TOKEN=your_github_token` in `backend/.env`.

#### Groq API Key Configuration
- Obtain an API key from the [Groq Console](https://console.groq.com/keys).
- Set `GROQ_API_KEY=your_groq_key` and `GROQ_MODEL=llama-3.3-70b-versatile` in `backend/.env`.

### 2. Frontend (`frontend/.env`)

Create or update `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
```

---

## PostgreSQL Database Setup

1. **Start PostgreSQL server** (default port `5432`).
2. **Create Database**:
   ```sql
   CREATE DATABASE codeforge_ai;
   ```
3. **Run Alembic Migrations**:
   ```powershell
   cd backend
   .\.venv\Scripts\Activate.ps1
   python -m alembic upgrade head
   ```

Verify database tables: `tasks`, `task_events`, `file_changes`, `test_runs`, `alembic_version`.

---

## Sandbox & Secure Execution Setup

CodeForge AI guarantees that untrusted repository code is never executed directly on the host machine:

- **Container Runtime**: Docker or Podman.
- **Pull Sandbox Image**:
  ```bash
  docker pull python:3.11-slim
  ```
- **Security Boundaries**:
  - Non-privileged mode (`--security-opt=no-new-privileges:true`).
  - Read-only root filesystem (`--read-only`) with isolated `--tmpfs /tmp`.
  - Enforced CPU & memory limits (`--cpus=2`, `--memory=2g`, `--pids-limit=128`).
  - No Docker socket or host filesystem access.
  - Strictly allowlisted test runner commands (`pytest`, `python -m unittest`, `npm test`, `cargo test`, `go test`).
  - **Refusal Fallback**: If Docker is not running, execution is refused with exit code `126` and `Execution Refused: No safe container runtime` in stderr, preserving host security.

---

## Application Startup Commands

### Terminal 1: Backend API Server
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --reload-dir app --port 8000
```
API Documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

### Terminal 2: Background Task Worker (Optional if ENABLE_IN_PROCESS_WORKER=true)
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.worker
```

### Terminal 3: Frontend Web Application
```powershell
cd frontend
npm install
npm run dev
```
Web Interface: [http://localhost:5173](http://localhost:5173)

---

## Running Automated Tests

### Backend Test Suite (123 Tests)
```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest tests/ -v
```

### Frontend Test Suite (12 Tests)
```powershell
cd frontend
npm test
```

### Frontend Production Build
```powershell
cd frontend
npm run build
```

---

## Manual End-to-End Acceptance Test Procedure

Follow these steps using the sample test repository `kuruvadhonendravarma-spec/codeforge-test-lab`:

1. **Open Frontend**: Navigate to [http://localhost:5173/new](http://localhost:5173/new).
2. **Validate Repository**:
   - Enter `https://github.com/kuruvadhonendravarma-spec/codeforge-test-lab`.
   - Click **Validate Repository**. The system inspects repo coordinates and automatically loads open issues.
3. **Select Issue #1**:
   - Issue #1: *"The add function returns an incorrect result"*.
   - Selecting the issue auto-fills the description: `add(a, b)` subtracts instead of adding; expects `add(2, 3) == 5`, `add(10, 5) == 15`, `add(-2, 5) == 3`.
4. **Submit Task**:
   - Click **Create Task**. The backend returns HTTP 201 with a real task ID and immediately redirects to the **Execution Center** (`/tasks/{id}`).
5. **Execution Monitoring**:
   - The UI polls state every 2 seconds.
   - Stepper advances: `investigating` &rarr; `planning` &rarr; `editing` &rarr; `testing` &rarr; `verifying` &rarr; `completed`.
   - Live chronological events appear in the Event Log.
6. **Inspect Code Changes**:
   - Click **Code Changes** (`/tasks/{id}/changes`).
   - The unified diff for `calculator.py` shows:
     ```diff
     -    return a - b  # Intentional bug
     +    return a + b
     ```
7. **Inspect Test Results**:
   - Click **Test Runs** (`/tasks/{id}/tests`).
   - Displays real exit code `0`, `PASSED`, and pytest output for `test_add`, `test_subtract`, `test_multiply`.
8. **Pull Request Approval Gate**:
   - Click **Pull Request** (`/tasks/{id}/pr`).
   - Summary, file change table, test evidence, and safety scans are displayed.
   - PR creation is **blocked** until the user explicitly checks the human approval confirmation.
   - CodeForge AI **never merges automatically**. Maintainers review and merge on GitHub.

---

## Known Limitations & Troubleshooting

| Symptom | Root Cause | Resolution |
| :--- | :--- | :--- |
| `fatal: Could not resolve host: github.com` | OS/DNS network outage or VPN interference. | Run `Resolve-DnsName github.com`. Verify internet connectivity. Once restored, click **Retry Task** in Execution Center. |
| `[object Object]` error in frontend | Unformatted API error payload. | **Resolved**. `formatApiErrorMessage()` and `getErrorMessage()` safely extract and format validation arrays, HTTP details, and network errors. |
| `Execution Refused: No safe container runtime (code 126)` | Docker daemon is not running on host. | Start Docker Desktop (`docker info`). The agent refuses host execution by design to prevent host compromise. |
| `HTTP 403: lacks push permissions` | GitHub token does not have write access to target repository. | Use a token with `repo` scope or target a repository you own. |
