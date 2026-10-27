from langgraph.graph import StateGraph, START, END
from langgraph.graph.state import CompiledStateGraph

from app.agent.state import AgentState
from app.agent.nodes import (
    investigate_node,
    plan_node,
    edit_node,
    test_node,
    diagnose_node,
    repair_node,
    verify_node,
    finish_node,
    should_diagnose_or_verify,
)


def create_codeforge_graph() -> CompiledStateGraph:
    """
    Constructs and compiles the CodeForge AI autonomous software engineering LangGraph.
    Explicitly defines nodes, conditional loops, bounded repair limits, and finish states.
    """
    workflow = StateGraph(AgentState)

    # Register workflow nodes
    workflow.add_node("investigate", investigate_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("edit", edit_node)
    workflow.add_node("test", test_node)
    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("repair", repair_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("finish", finish_node)

    # Linear workflow sequence
    workflow.add_edge(START, "investigate")
    workflow.add_edge("investigate", "plan")
    workflow.add_edge("plan", "edit")
    workflow.add_edge("edit", "test")

    # Bounded conditional router after test execution
    workflow.add_conditional_edges(
        "test",
        should_diagnose_or_verify,
        {
            "verify": "verify",
            "diagnose": "diagnose",
            "finish": "finish",
        },
    )

    # Corrective repair loop (bounded by max_repairs in should_diagnose_or_verify)
    workflow.add_edge("diagnose", "repair")
    workflow.add_edge("repair", "test")

    # Verification and completion
    workflow.add_edge("verify", "finish")
    workflow.add_edge("finish", END)

    return workflow.compile()
