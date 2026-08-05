"""
src/agents.py

Implementation of 6 Sub-Agents for Milestone 2:
1. Coordinator Agent: Case ingestion and state graph management.
2. Order & Seller Agent: CSV lookup tools and late handoff check.
3. Payment Agent: Payment CSV tools and financial reconciliation.
4. Delivery Agent: Timestamp lateness comparison and delay responsibility.
5. Policy Agent: Invoking EC_POLICY_V1 priority rules engine.
6. Verifier Agent: Validating output against Pydantic schema (DisputeOutput).
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from langchain_groq import ChatGroq

from src.schemas import (
    DisputeState,
    DisputeOutput,
    Assessment,
    AffectedEntities,
    RootCauseAnalysis,
    RankedCause,
    ResponsibleParty,
    FinancialResolution,
)
from src.tools import (
    get_order_details,
    get_order_items,
    get_order_payments,
    get_seller_details,
    check_delivery_lateness,
    check_carrier_pickup_lateness,
    reconcile_financials,
)
from src.policy import (
    evaluate_policy,
    generate_evidence_ids,
    generate_affected_entities,
)
from src.logger import ExecutionLogger, measure_latency

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("agents")
MODEL_NAME = os.getenv("GROQ_MODEL", os.getenv("MODEL_NAME", "llama-3.1-8b-instant"))


def get_groq_llm(temperature: Optional[float] = None) -> Optional[ChatGroq]:
    """
    Safely retrieves a ChatGroq instance if GROQ_API_KEY is configured.
    Returns None if key is missing or initialization fails.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not api_key.strip():
        return None
    if temperature is None:
        try:
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))
        except ValueError:
            temperature = 0.0
    try:
        return ChatGroq(
            model=MODEL_NAME,
            groq_api_key=api_key.strip(),
            temperature=temperature,
            max_tokens=1024,
        )
    except Exception as e:
        logger.warning(f"Failed to initialize ChatGroq model {MODEL_NAME}: {e}")
        return None


# =============================================================================
# 1. Coordinator Agent
# =============================================================================
def coordinator_agent(state: DisputeState) -> Dict[str, Any]:
    """Case ingestion and pipeline initialization."""
    exec_logger = ExecutionLogger()
    elapsed = {}

    with measure_latency() as elapsed:
        input_data = state.get("input_data", {})
        case_id = state.get("case_id") or input_data.get("case_id", "UNKNOWN_CASE")
        req = input_data.get("customer_request", {}) if isinstance(input_data, dict) else {}
        claimed_order_id = (
            input_data.get("order_id")
            if isinstance(input_data, dict) and input_data.get("order_id")
            else req.get("claimed_order_id")
        )

        status = "SUCCESS"
        errors = []
        if not claimed_order_id:
            errors.append(f"Missing claimed_order_id in case {case_id}")
            status = "WARNING"

        input_summary = {"case_id": case_id, "claimed_order_id": claimed_order_id}
        output_summary = {"case_id": case_id, "status": "ingested"}

    trace_step = exec_logger.log_step(
        case_id=case_id,
        agent_name="Coordinator",
        action="ingest_case",
        input_summary=input_summary,
        output_summary=output_summary,
        status=status,
        latency_ms=elapsed["ms"]
    )

    res = {
        "case_id": case_id,
        "trace_steps": [trace_step],
    }
    if errors:
        res["errors"] = errors
    return res


# =============================================================================
# 2. Order & Seller Agent
# =============================================================================
def order_seller_agent(state: DisputeState) -> Dict[str, Any]:
    """Queries order details, item details, seller details, and evaluates late seller handoff."""
    exec_logger = ExecutionLogger()
    case_id = state.get("case_id", "UNKNOWN_CASE")
    input_data = state.get("input_data", {})
    req = input_data.get("customer_request", {}) if isinstance(input_data, dict) else {}
    claimed_order_id = (
        input_data.get("order_id")
        if isinstance(input_data, dict) and input_data.get("order_id")
        else req.get("claimed_order_id")
    )

    elapsed = {}
    with measure_latency() as elapsed:
        if not claimed_order_id:
            err_msg = "OrderSellerAgent: No claimed_order_id in state."
            output_summary = {"found": False, "error": err_msg}
            trace_step = exec_logger.log_step(
                case_id=case_id,
                agent_name="OrderSellerAgent",
                action="query_order_and_items",
                input_summary={"case_id": case_id},
                output_summary=output_summary,
                status="ERROR",
                latency_ms=elapsed["ms"]
            )
            return {
                "order_info": {"found": False, "error": err_msg},
                "errors": [err_msg],
                "trace_steps": [trace_step]
            }

        # Execute CSV lookup tools
        order_details = get_order_details.invoke({"order_id": claimed_order_id})
        items_data = get_order_items.invoke({"order_id": claimed_order_id})

        seller_ids = items_data.get("seller_ids", [])
        sellers_details = []
        for sid in seller_ids:
            sdet = get_seller_details.invoke({"seller_id": sid})
            sellers_details.append(sdet)

        # Evaluate seller late handoff
        carrier_date = order_details.get("order_delivered_carrier_date")
        items = items_data.get("items", [])
        carrier_pickup_after_limit = False
        violating_seller_ids = []

        if carrier_date and items:
            for item in items:
                limit_date = item.get("shipping_limit_date")
                if limit_date and check_carrier_pickup_lateness(carrier_date, limit_date):
                    carrier_pickup_after_limit = True
                    sid = item.get("seller_id")
                    if sid and sid not in violating_seller_ids:
                        violating_seller_ids.append(sid)

        # LLM Reasoning or Fallback
        llm = get_groq_llm()
        execution_mode = "LLM" if llm is not None else "FALLBACK"
        reasoning = ""

        if llm is not None:
            try:
                prompt = (
                    f"Analyze order {claimed_order_id}:\n"
                    f"Order Status: {order_details.get('order_status')}\n"
                    f"Carrier Pickup: {carrier_date}\n"
                    f"Items Count: {items_data.get('item_count')}\n"
                    f"Carrier Pickup After Shipping Limit: {carrier_pickup_after_limit}\n"
                    "Provide a brief 1-2 sentence summary."
                )
                resp = llm.invoke(prompt)
                reasoning = str(resp.content).strip()
            except Exception as e:
                execution_mode = "FALLBACK"
                reasoning = f"LLM error: {e}. Evaluated deterministically."
        else:
            reasoning = (
                f"Order {claimed_order_id} status '{order_details.get('order_status')}'. "
                f"Carrier pickup after limit: {carrier_pickup_after_limit}."
            )

        order_info = {
            "order_id": claimed_order_id,
            "found": order_details.get("found", False),
            "order_status": order_details.get("order_status"),
            "order_purchase_timestamp": order_details.get("order_purchase_timestamp"),
            "order_approved_at": order_details.get("order_approved_at"),
            "order_delivered_carrier_date": carrier_date,
            "order_delivered_customer_date": order_details.get("order_delivered_customer_date"),
            "order_estimated_delivery_date": order_details.get("order_estimated_delivery_date"),
            "items": items,
            "item_count": items_data.get("item_count", 0),
            "item_total_brl": items_data.get("item_total_brl", 0.0),
            "freight_total_brl": items_data.get("freight_total_brl", 0.0),
            "seller_ids": seller_ids,
            "sellers_details": sellers_details,
            "carrier_pickup_after_limit": carrier_pickup_after_limit,
            "violating_seller_ids": violating_seller_ids,
            "execution_mode": execution_mode,
            "reasoning": reasoning,
        }

        output_summary = {
            "order_id": claimed_order_id,
            "order_status": order_details.get("order_status"),
            "item_count": len(items),
            "item_total_brl": items_data.get("item_total_brl", 0.0),
            "freight_total_brl": items_data.get("freight_total_brl", 0.0),
            "carrier_pickup_after_limit": carrier_pickup_after_limit,
            "violating_seller_ids": violating_seller_ids,
        }

    trace_step = exec_logger.log_step(
        case_id=case_id,
        agent_name="OrderSellerAgent",
        action="query_order_and_items",
        input_summary={"claimed_order_id": claimed_order_id},
        output_summary=output_summary,
        status="SUCCESS",
        latency_ms=elapsed["ms"]
    )

    return {
        "order_info": order_info,
        "trace_steps": [trace_step],
    }


# =============================================================================
# 3. Payment Agent
# =============================================================================
def payment_agent(state: DisputeState) -> Dict[str, Any]:
    """Queries payment details and reconciles payment_total vs (item_total + freight_total)."""
    exec_logger = ExecutionLogger()
    case_id = state.get("case_id", "UNKNOWN_CASE")
    order_info = state.get("order_info") or {}
    order_id = order_info.get("order_id")

    elapsed = {}
    with measure_latency() as elapsed:
        if not order_id:
            err_msg = "PaymentAgent: Missing order_id from order_info."
            output_summary = {"found": False, "error": err_msg}
            trace_step = exec_logger.log_step(
                case_id=case_id,
                agent_name="PaymentAgent",
                action="reconcile_payments",
                input_summary={"case_id": case_id},
                output_summary=output_summary,
                status="ERROR",
                latency_ms=elapsed["ms"]
            )
            return {
                "payment_info": {"found": False, "error": err_msg},
                "errors": [err_msg],
                "trace_steps": [trace_step]
            }

        payments_data = get_order_payments.invoke({"order_id": order_id})
        payment_total = payments_data.get("payment_total_brl", 0.0)
        item_total = order_info.get("item_total_brl", 0.0)
        freight_total = order_info.get("freight_total_brl", 0.0)

        is_reconciled = reconcile_financials(payment_total, item_total, freight_total, tolerance=0.10)
        expected_total = round(item_total + freight_total, 2)
        discrepancy = round(payment_total - expected_total, 2)

        llm = get_groq_llm()
        execution_mode = "LLM" if llm is not None else "FALLBACK"
        reasoning = ""

        if llm is not None:
            try:
                prompt = (
                    f"Reconcile payments for order {order_id}:\n"
                    f"Payments Total: {payment_total} BRL\n"
                    f"Items Total: {item_total} BRL, Freight Total: {freight_total} BRL\n"
                    f"Expected Total: {expected_total} BRL\n"
                    f"Reconciled (<=0.10 BRL tol): {is_reconciled}\n"
                    "Provide a brief 1-sentence reconciliation status."
                )
                resp = llm.invoke(prompt)
                reasoning = str(resp.content).strip()
            except Exception as e:
                execution_mode = "FALLBACK"
                reasoning = f"LLM error: {e}. Reconciled deterministically."
        else:
            reasoning = (
                f"Payments total {payment_total} BRL vs expected {expected_total} BRL. "
                f"Reconciled: {is_reconciled}."
            )

        payment_info = {
            "order_id": order_id,
            "payments": payments_data.get("payments", []),
            "payment_count": payments_data.get("payment_count", 0),
            "payment_total_brl": payment_total,
            "item_total_brl": item_total,
            "freight_total_brl": freight_total,
            "expected_total_brl": expected_total,
            "is_reconciled": is_reconciled,
            "discrepancy_brl": discrepancy,
            "execution_mode": execution_mode,
            "reasoning": reasoning,
        }

        output_summary = {
            "order_id": order_id,
            "payment_count": payments_data.get("payment_count", 0),
            "payment_total_brl": payment_total,
            "expected_total_brl": expected_total,
            "is_reconciled": is_reconciled,
            "discrepancy_brl": discrepancy,
        }

    trace_step = exec_logger.log_step(
        case_id=case_id,
        agent_name="PaymentAgent",
        action="reconcile_payments",
        input_summary={"order_id": order_id, "item_total": item_total, "freight_total": freight_total},
        output_summary=output_summary,
        status="SUCCESS",
        latency_ms=elapsed["ms"]
    )

    return {
        "payment_info": payment_info,
        "trace_steps": [trace_step],
    }


# =============================================================================
# 4. Delivery Agent
# =============================================================================
def delivery_agent(state: DisputeState) -> Dict[str, Any]:
    """Compares delivery dates vs estimated date and evaluates delay responsibility."""
    exec_logger = ExecutionLogger()
    case_id = state.get("case_id", "UNKNOWN_CASE")
    order_info = state.get("order_info") or {}
    order_id = order_info.get("order_id", "")

    elapsed = {}
    with measure_latency() as elapsed:
        deliv_cust = order_info.get("order_delivered_customer_date")
        est_deliv = order_info.get("order_estimated_delivery_date")
        deliv_carr = order_info.get("order_delivered_carrier_date")
        carrier_pickup_after_limit = bool(order_info.get("carrier_pickup_after_limit", False))

        is_delivered_after_estimate = check_delivery_lateness(deliv_cust, est_deliv) or False

        if is_delivered_after_estimate:
            if carrier_pickup_after_limit:
                delay_responsibility = "seller"
                root_cause_code = "SELLER_HANDOFF_AFTER_LIMIT"
            else:
                delay_responsibility = "logistics_provider"
                root_cause_code = "CARRIER_DELIVERED_AFTER_ESTIMATE"
        else:
            delay_responsibility = "none"
            root_cause_code = "DELIVERY_WITHIN_ESTIMATE"

        llm = get_groq_llm()
        execution_mode = "LLM" if llm is not None else "FALLBACK"
        reasoning = ""

        if llm is not None:
            try:
                prompt = (
                    f"Evaluate delivery lateness for order {order_id}:\n"
                    f"Delivered Customer Date: {deliv_cust}\n"
                    f"Estimated Delivery Date: {est_deliv}\n"
                    f"Delivered Carrier Date: {deliv_carr}\n"
                    f"Late Delivery: {is_delivered_after_estimate}\n"
                    f"Carrier Pickup After Limit: {carrier_pickup_after_limit}\n"
                    f"Responsibility: {delay_responsibility}\n"
                    "Summarize delivery assessment in 1 sentence."
                )
                resp = llm.invoke(prompt)
                reasoning = str(resp.content).strip()
            except Exception as e:
                execution_mode = "FALLBACK"
                reasoning = f"LLM error: {e}. Evaluated delivery deterministically."
        else:
            reasoning = (
                f"Delivered after estimate: {is_delivered_after_estimate}. "
                f"Responsibility: {delay_responsibility} ({root_cause_code})."
            )

        delivery_info = {
            "order_id": order_id,
            "is_delivered_after_estimate": is_delivered_after_estimate,
            "carrier_pickup_after_limit": carrier_pickup_after_limit,
            "delivered_customer_date": deliv_cust,
            "estimated_delivery_date": est_deliv,
            "delivered_carrier_date": deliv_carr,
            "delay_responsibility": delay_responsibility,
            "root_cause_code": root_cause_code,
            "execution_mode": execution_mode,
            "reasoning": reasoning,
        }

        output_summary = {
            "order_id": order_id,
            "is_delivered_after_estimate": is_delivered_after_estimate,
            "carrier_pickup_after_limit": carrier_pickup_after_limit,
            "delay_responsibility": delay_responsibility,
            "root_cause_code": root_cause_code,
        }

    trace_step = exec_logger.log_step(
        case_id=case_id,
        agent_name="DeliveryAgent",
        action="evaluate_delivery_lateness",
        input_summary={"order_id": order_id, "delivered_customer_date": deliv_cust, "estimated_delivery_date": est_deliv},
        output_summary=output_summary,
        status="SUCCESS",
        latency_ms=elapsed["ms"]
    )

    return {
        "delivery_info": delivery_info,
        "trace_steps": [trace_step],
    }


# =============================================================================
# 5. Policy Agent
# =============================================================================
def policy_agent(state: DisputeState) -> Dict[str, Any]:
    """Applies EC_POLICY_V1 business rules in priority order (Rules 1 to 6)."""
    exec_logger = ExecutionLogger()
    case_id = state.get("case_id", "UNKNOWN_CASE")
    order_info = state.get("order_info") or {}
    payment_info = state.get("payment_info") or {}
    delivery_info = state.get("delivery_info") or {}

    elapsed = {}
    with measure_latency() as elapsed:
        order_status = order_info.get("order_status", "")
        payment_total = payment_info.get("payment_total_brl", 0.0)
        item_total = order_info.get("item_total_brl", 0.0)
        freight_total = order_info.get("freight_total_brl", 0.0)
        payment_count = payment_info.get("payment_count", 0)

        is_delivered_after_estimate = bool(delivery_info.get("is_delivered_after_estimate", False))
        carrier_pickup_after_limit = bool(delivery_info.get("carrier_pickup_after_limit", False))
        violating_seller_ids = order_info.get("violating_seller_ids", [])

        # Collect shipping limit dates from items for confidence calculation
        items_list = order_info.get("items", [])
        shipping_limit_dates = [
            it.get("shipping_limit_date") for it in items_list
            if it.get("shipping_limit_date")
        ]

        # Evaluate priority policy rules
        finding = evaluate_policy(
            order_status=order_status,
            payment_total_brl=payment_total,
            item_total_brl=item_total,
            freight_total_brl=freight_total,
            payment_rows_count=payment_count,
            is_delivered_after_estimate=is_delivered_after_estimate,
            carrier_pickup_after_limit=carrier_pickup_after_limit,
            violating_seller_ids=violating_seller_ids,
            delivered_customer_date=delivery_info.get("delivered_customer_date"),
            estimated_delivery_date=delivery_info.get("estimated_delivery_date"),
            delivered_carrier_date=order_info.get("order_delivered_carrier_date"),
            shipping_limit_dates=shipping_limit_dates,
        )

        llm = get_groq_llm()
        execution_mode = "LLM" if llm is not None else "FALLBACK"
        reasoning = ""

        if llm is not None:
            try:
                prompt = (
                    f"Explain business policy decision (EC_POLICY_V1):\n"
                    f"Matched Primary Issue: {finding.primary_issue}\n"
                    f"Root Cause Code: {finding.root_cause_code}\n"
                    f"Responsible Party: {finding.responsible_party} ({finding.responsible_party_ids})\n"
                    f"Recommended Refund: {finding.recommended_refund_brl} BRL\n"
                    f"Resolution Actions: {finding.resolution_actions}\n"
                    "Provide a brief executive justification."
                )
                resp = llm.invoke(prompt)
                reasoning = str(resp.content).strip()
            except Exception as e:
                execution_mode = "FALLBACK"
                reasoning = f"LLM error: {e}. Applied policy engine deterministically."
        else:
            reasoning = (
                f"Policy rule '{finding.primary_issue}' matched. "
                f"Refund: {finding.recommended_refund_brl} BRL. Party: {finding.responsible_party}."
            )

        policy_finding_dict = {
            "primary_issue": finding.primary_issue,
            "root_cause_code": finding.root_cause_code,
            "responsible_party": finding.responsible_party,
            "responsible_party_ids": finding.responsible_party_ids,
            "recommended_refund_brl": finding.recommended_refund_brl,
            "resolution_actions": finding.resolution_actions,
            "case_status": finding.case_status,
            "evidence_policy_id": finding.evidence_policy_id,
            "confidence": finding.confidence,
            "execution_mode": execution_mode,
            "reasoning": reasoning,
        }

        output_summary = {
            "primary_issue": finding.primary_issue,
            "root_cause_code": finding.root_cause_code,
            "responsible_party": finding.responsible_party,
            "recommended_refund_brl": finding.recommended_refund_brl,
            "case_status": finding.case_status,
        }

    trace_step = exec_logger.log_step(
        case_id=case_id,
        agent_name="PolicyAgent",
        action="evaluate_ec_policy_v1",
        input_summary={
            "order_status": order_status,
            "payment_total": payment_total,
            "is_delivered_after_estimate": is_delivered_after_estimate,
        },
        output_summary=output_summary,
        status="SUCCESS",
        latency_ms=elapsed["ms"]
    )

    return {
        "policy_finding": policy_finding_dict,
        "trace_steps": [trace_step],
    }


# =============================================================================
# 6. Verifier Agent
# =============================================================================
def verifier_agent(state: DisputeState) -> Dict[str, Any]:
    """Validates final dispute resolution payload against DisputeOutput Pydantic schema."""
    exec_logger = ExecutionLogger()
    case_id = state.get("case_id", "UNKNOWN_CASE")
    order_info = state.get("order_info") or {}
    payment_info = state.get("payment_info") or {}
    policy_finding = state.get("policy_finding") or {}

    elapsed = {}
    with measure_latency() as elapsed:
        order_id = order_info.get("order_id", "")
        items = order_info.get("items", [])
        payments = payment_info.get("payments", [])
        sellers = order_info.get("seller_ids", [])

        primary_issue = policy_finding.get("primary_issue", "unsupported_claim")
        confidence = 1.0
        root_cause_code = policy_finding.get("root_cause_code", "NO_POLICY_MATCH")
        resp_party = policy_finding.get("responsible_party", "none")
        resp_party_ids = policy_finding.get("responsible_party_ids", [])
        refund_brl = float(policy_finding.get("recommended_refund_brl", 0.0))
        actions = policy_finding.get("resolution_actions", ["reject_claim"])

        # Enforce exact cross-field logic: refund > 0 -> action_required, else no_action
        case_status = "action_required" if refund_brl > 0.0 else "no_action"

        # Build Pydantic models
        assessment = Assessment(
            primary_issue=primary_issue,
            case_status=case_status,
            confidence=confidence,
        )

        if primary_issue == "late_delivery_seller":
            evidence_sellers = sellers
        else:
            evidence_sellers = []

        entity_sellers = sellers

        affected_dict = generate_affected_entities(order_id, items, payments, entity_sellers)
        affected_entities = AffectedEntities(
            order_ids=affected_dict["order_ids"],
            item_ids=affected_dict["item_ids"],
            seller_ids=affected_dict["seller_ids"],
            payment_ids=affected_dict["payment_ids"],
        )

        # When no one is responsible, BTC expects empty array []
        if resp_party == "none":
            responsible_parties_list = []
        else:
            responsible_parties_list = [ResponsibleParty(party_type=resp_party, party_id=pid) for pid in resp_party_ids]

        root_cause_analysis = RootCauseAnalysis(
            ranked_causes=[RankedCause(cause_code=root_cause_code, rank=1)],
            responsible_parties=responsible_parties_list,
        )

        evidence_ids = generate_evidence_ids(order_id, items, payments, evidence_sellers, root_cause_code)

        financial_resolution = FinancialResolution(
            currency="BRL",
            item_total_brl=float(order_info.get("item_total_brl", 0.0)),
            freight_total_brl=float(order_info.get("freight_total_brl", 0.0)),
            payment_total_brl=float(payment_info.get("payment_total_brl", 0.0)),
            recommended_refund_brl=refund_brl,
        )

        dispute_output = DisputeOutput(
            case_id=case_id,
            assessment=assessment,
            affected_entities=affected_entities,
            root_cause_analysis=root_cause_analysis,
            evidence_ids=evidence_ids,
            financial_resolution=financial_resolution,
            resolution_actions=actions,
        )

        final_output_dict = dispute_output.model_dump()

        output_summary = {
            "validation": "SUCCESS",
            "case_id": case_id,
            "case_status": case_status,
            "recommended_refund_brl": refund_brl,
        }

    trace_step = exec_logger.log_step(
        case_id=case_id,
        agent_name="VerifierAgent",
        action="validate_and_finalize",
        input_summary={"case_id": case_id, "primary_issue": primary_issue},
        output_summary=output_summary,
        status="SUCCESS",
        latency_ms=elapsed["ms"]
    )

    return {
        "final_output": final_output_dict,
        "trace_steps": [trace_step],
    }
