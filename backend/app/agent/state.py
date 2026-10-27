from typing import TypedDict, Optional, List, Dict, Any


class AgentState(TypedDict, total=False):
    """
    Typed state representation passed across all LangGraph nodes in CodeForge AI.
    Tracks metadata, generated vs applied vs verified changes, and repair iteration bounds.
    """

    # Task identity and repository coordinates
    task_id: int
    repository_url: str
    owner: str
    repo: str
    issue_number: Optional[int]
    issue_title: Optional[str]
    issue_body: Optional[str]
    task_description: str
    acceptance_criteria: Optional[str]
    required_files: List[str]
    required_symbols: List[str]

    # Workflow lifecycle and bounded iteration controls
    status: str
    current_stage: str
    retry_count: int
    max_retries: int
    repair_count: int
    max_repairs: int
    is_cancelled: bool

    # Stage 1: Investigation
    relevant_files: List[str]
    investigation_summary: str
    code_context: str

    # Stage 2: Planning
    plan: str

    # Stage 3: Editing (Distinguishes proposed from applied changes)
    proposed_changes: Dict[str, str]   # relative_file_path -> generated_content
    applied_changes: Dict[str, str]    # relative_file_path -> applied_content
    original_contents: Dict[str, str]  # relative_file_path -> original_content
    file_diffs: Dict[str, str]         # relative_file_path -> unified_diff_text

    # Stage 4: Testing
    test_command: str
    test_passed: Optional[bool]
    test_exit_code: Optional[int]
    test_stdout: Optional[str]
    test_stderr: Optional[str]

    # Stage 5: Diagnosis
    diagnosis: Optional[str]

    # Stage 6: Repair
    repair_summary: Optional[str]

    # Stage 7: Verification
    verification_passed: bool
    verification_evidence: Optional[str]
    safety_checks_passed: bool

    # Execution events and error tracking
    error_summary: Optional[str]
    events: List[Dict[str, Any]]
