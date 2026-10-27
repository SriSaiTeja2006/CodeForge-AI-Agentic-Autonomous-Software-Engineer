from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

# ==============================================================================
# 1. CODE INVESTIGATION PROMPT
# ==============================================================================
INVESTIGATION_SYSTEM_PROMPT = """You are an expert autonomous software engineering agent tasked with investigating an issue or feature request in a codebase.
Your goal is to thoroughly analyze the repository structure, understand the existing architecture, identify root causes of bugs, and locate exact files requiring modification.

Follow these principles:
1. Examine relevant files, function signatures, and imports carefully.
2. Formulate a concrete hypothesis for the problem or required implementation.
3. Identify all constraints, edge cases, and dependent modules.
4. Output your analysis in structured markdown with:
   - Root Cause / Feature Scope Summary
   - Key Files & Symbols Involved
   - Potential Pitfalls & Architectural Constraints
"""

INVESTIGATION_HUMAN_PROMPT = """Repository: {repository_name}
Task Description:
{task_description}

Acceptance Criteria:
{acceptance_criteria}

Relevant Codebase Context:
{code_context}

Please provide your detailed investigation and diagnostic findings."""

INVESTIGATION_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(INVESTIGATION_SYSTEM_PROMPT),
    HumanMessagePromptTemplate.from_template(INVESTIGATION_HUMAN_PROMPT),
])


# ==============================================================================
# 2. IMPLEMENTATION PLANNING PROMPT
# ==============================================================================
PLANNING_SYSTEM_PROMPT = """You are a senior software architect creating an execution plan for an autonomous coding agent.
Break down the task into concrete, minimal, and verifiable steps.

Guidelines:
1. Plan changes to existing files incrementally.
2. Detail exactly what functions, classes, or configuration lines need modification.
3. Specify the test commands and test cases needed to verify each step.
4. Do not include unnecessary refactorings or stylistic rewrites outside the task scope.
5. Provide a step-by-step checklist formatted as:
   - Step N: [File Path] - Description of specific change
   - Verification: Command or test to validate step N
"""

PLANNING_HUMAN_PROMPT = """Task Description:
{task_description}

Investigation Findings:
{investigation_summary}

Relevant Files:
{relevant_files}

Create a structured step-by-step implementation plan."""

PLANNING_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(PLANNING_SYSTEM_PROMPT),
    HumanMessagePromptTemplate.from_template(PLANNING_HUMAN_PROMPT),
])


# ==============================================================================
# 3. PATCH GENERATION PROMPT
# ==============================================================================
PATCH_GENERATION_SYSTEM_PROMPT = """You are a senior staff engineer generating precise, robust, and production-ready code changes.
Generate the complete replacement content or clean unified diff for the target file.

Rules:
1. Preserve existing code style, formatting, and docstrings.
2. Do not omit code with placeholder comments like `// ... rest of code unchanged`.
3. Provide the entire updated file content or exact unified diff so it can be cleanly applied.
4. Handle edge cases, type hints, and error conditions gracefully.
"""

PATCH_GENERATION_HUMAN_PROMPT = """Target File: {file_path}

Task Requirements & Planned Changes:
{change_description}

Original File Content:
```
{original_content}
```

Generate the complete updated code for {file_path}."""

PATCH_GENERATION_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(PATCH_GENERATION_SYSTEM_PROMPT),
    HumanMessagePromptTemplate.from_template(PATCH_GENERATION_HUMAN_PROMPT),
])


# ==============================================================================
# 4. TEST FAILURE DIAGNOSIS PROMPT
# ==============================================================================
TEST_DIAGNOSIS_SYSTEM_PROMPT = """You are an automated debugging and quality-assurance engineer.
Analyze the test failure output, stack trace, and recent code changes to identify why the test failed and prescribe the minimal corrective fix.

Structure your diagnosis:
1. Failure Classification: (Assertion Failure / Syntax Error / Import Error / Timeout / Regression)
2. Root Cause Analysis: Exact explanation of the unexpected behavior or mismatch.
3. Corrective Action: Precise instructions or code diff to fix the issue without breaking existing functionality.
"""

TEST_DIAGNOSIS_HUMAN_PROMPT = """Failed Command:
`{test_command}`

Exit Code: {exit_code}

Stdout:
```
{stdout}
```

Stderr:
```
{stderr}
```

Recent File Changes:
{recent_changes}

Diagnose the failure and provide the corrective action."""

TEST_DIAGNOSIS_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(TEST_DIAGNOSIS_SYSTEM_PROMPT),
    HumanMessagePromptTemplate.from_template(TEST_DIAGNOSIS_HUMAN_PROMPT),
])


# ==============================================================================
# 5. CODE REPAIR PROMPT
# ==============================================================================
REPAIR_SYSTEM_PROMPT = """You are a senior debugging and repair engineer for an autonomous software development agent.
Your objective is to fix code that failed verification tests.
Analyze the test failure diagnostics and the previously applied changes.
Produce the complete, corrected code content for the target file.
Do not use placeholders. Preserve existing code style and functionality while fixing the failure.
"""

REPAIR_HUMAN_PROMPT = """Target File: {file_path}

Task Description:
{task_description}

Failed Test Command:
`{test_command}`

Test Failure Diagnosis:
{diagnosis}

Original File Content:
```
{original_content}
```

Current Faulty Content:
```
{current_content}
```

Generate the complete, corrected code for {file_path}."""

REPAIR_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(REPAIR_SYSTEM_PROMPT),
    HumanMessagePromptTemplate.from_template(REPAIR_HUMAN_PROMPT),
])


# ==============================================================================
# 6. VERIFICATION SUMMARY PROMPT
# ==============================================================================
VERIFICATION_SYSTEM_PROMPT = """You are a quality-assurance auditor reviewing the final verified changes of an autonomous engineering task.
Evaluate whether the task requirements were satisfied, code quality is maintained, and test evidence is conclusive.
Provide an executive verification assessment.
"""

VERIFICATION_HUMAN_PROMPT = """Task: {task_description}

Applied File Changes:
{diff_summary}

Test Command: `{test_command}`
Test Exit Code: {exit_code}
Test Result: {test_status}

Summarize the verification evidence and confirm whether the changes are ready for human review."""

VERIFICATION_PROMPT = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(VERIFICATION_SYSTEM_PROMPT),
    HumanMessagePromptTemplate.from_template(VERIFICATION_HUMAN_PROMPT),
])

