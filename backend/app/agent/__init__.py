"""LangGraph and LangChain agent architecture module."""
from app.agent.state import AgentState
from app.agent.tools import WorkspaceTools, compute_unified_diff
from app.agent.graph import create_codeforge_graph
from app.agent.prompts import (
    INVESTIGATION_PROMPT,
    INVESTIGATION_SYSTEM_PROMPT,
    INVESTIGATION_HUMAN_PROMPT,
    PLANNING_PROMPT,
    PLANNING_SYSTEM_PROMPT,
    PLANNING_HUMAN_PROMPT,
    PATCH_GENERATION_PROMPT,
    PATCH_GENERATION_SYSTEM_PROMPT,
    PATCH_GENERATION_HUMAN_PROMPT,
    TEST_DIAGNOSIS_PROMPT,
    TEST_DIAGNOSIS_SYSTEM_PROMPT,
    TEST_DIAGNOSIS_HUMAN_PROMPT,
    REPAIR_PROMPT,
    VERIFICATION_PROMPT,
)

__all__ = [
    "AgentState",
    "WorkspaceTools",
    "compute_unified_diff",
    "create_codeforge_graph",
    "INVESTIGATION_PROMPT",
    "INVESTIGATION_SYSTEM_PROMPT",
    "INVESTIGATION_HUMAN_PROMPT",
    "PLANNING_PROMPT",
    "PLANNING_SYSTEM_PROMPT",
    "PLANNING_HUMAN_PROMPT",
    "PATCH_GENERATION_PROMPT",
    "PATCH_GENERATION_SYSTEM_PROMPT",
    "PATCH_GENERATION_HUMAN_PROMPT",
    "TEST_DIAGNOSIS_PROMPT",
    "TEST_DIAGNOSIS_SYSTEM_PROMPT",
    "TEST_DIAGNOSIS_HUMAN_PROMPT",
    "REPAIR_PROMPT",
    "VERIFICATION_PROMPT",
]

