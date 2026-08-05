"""
src/graph.py

LangGraph StateGraph workflow assembly and pipeline runner for Milestone 2.
Coordinates 6 specialist agents: Coordinator -> Order/Seller -> Payment -> Delivery -> Policy -> Verifier -> END.
"""

from typing import Dict, Any
from langgraph.graph import StateGraph, START, END

from src.schemas import DisputeState
from src.agents import (
    coordinator_agent,
    order_seller_agent,
    payment_agent,
    delivery_agent,
    policy_agent,
    verifier_agent,
)


def build_dispute_graph():
    """
    Assembles and compiles the LangGraph StateGraph workflow using the 6 specialist agents.
    """
    builder = StateGraph(DisputeState)

    # Add agent nodes
    builder.add_node("coordinator", coordinator_agent)
    builder.add_node("order_seller", order_seller_agent)
    builder.add_node("payment", payment_agent)
    builder.add_node("delivery", delivery_agent)
    builder.add_node("policy", policy_agent)
    builder.add_node("verifier", verifier_agent)

    # Define sequential execution flow
    builder.add_edge(START, "coordinator")
    builder.add_edge("coordinator", "order_seller")
    builder.add_edge("order_seller", "payment")
    builder.add_edge("payment", "delivery")
    builder.add_edge("delivery", "policy")
    builder.add_edge("policy", "verifier")
    builder.add_edge("verifier", END)

    return builder.compile()


def run_dispute_pipeline(case_data: dict) -> dict:
    """
    Executes the dispute resolution multi-agent pipeline for a single input case dictionary.
    
    Args:
        case_data: Dictionary containing input case information (e.g. from input/EC_xxx.json).

    Returns:
        Validated DisputeOutput dictionary produced by VerifierAgent.
    """
    case_id = case_data.get("case_id", "UNKNOWN")
    initial_state: DisputeState = {
        "case_id": case_id,
        "input_data": case_data,
        "order_info": None,
        "payment_info": None,
        "delivery_info": None,
        "policy_finding": None,
        "final_output": None,
        "trace_steps": [],
        "errors": [],
    }

    graph = build_dispute_graph()
    final_state = graph.invoke(initial_state)

    return final_state.get("final_output") or {}
