"""
src/policy.py - EC_POLICY_V1 Business Rules Engine

Provides deterministic evaluation of e-commerce dispute policy rules in priority order (Priority 1 to 6),
financial calculations, date parsing helpers, and evidence ID formatting.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd


@dataclass
class PolicyFinding:
    primary_issue: str
    root_cause_code: str
    responsible_party: str          # 'platform', 'seller', 'logistics_provider', or 'none'
    responsible_party_ids: List[str]       # list of seller_ids, or ['OLIST_PLATFORM'], ['LOGISTICS_PROVIDER'], or []
    recommended_refund_brl: float
    resolution_actions: List[str]
    case_status: str                # 'action_required' if refund > 0 else 'no_action'
    evidence_policy_id: str         # e.g. 'policy:SELLER_HANDOFF_AFTER_LIMIT'
    confidence: float = 1.0


def parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Helper to parse ISO/Olist timestamp strings into naive datetime objects."""
    if not dt_str or pd.isna(dt_str) or not isinstance(dt_str, str):
        return None
    clean_str = dt_str.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(clean_str[:19], fmt[:19] if len(clean_str) >= 19 else fmt)
        except ValueError:
            continue
    return None


def calculate_financial_totals(items: List[Dict[str, Any]], payments: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Computes rounded 2-decimal BRL monetary totals for items, freight, and payments.
    If items is empty, item_total_brl and freight_total_brl are 0.0.
    """
    if items:
        item_total = sum(float(i.get("price", i.get("price_brl", 0.0)) or 0.0) for i in items)
        freight_total = sum(float(i.get("freight_value", i.get("freight_value_brl", 0.0)) or 0.0) for i in items)
    else:
        item_total = 0.0
        freight_total = 0.0

    if payments:
        payment_total = sum(float(p.get("payment_value", p.get("payment_value_brl", 0.0)) or 0.0) for p in payments)
    else:
        payment_total = 0.0

    return {
        "item_total_brl": round(item_total, 2),
        "freight_total_brl": round(freight_total, 2),
        "payment_total_brl": round(payment_total, 2),
    }


def determine_delivery_flags(
    delivered_customer_date: Optional[str],
    estimated_delivery_date: Optional[str],
    delivered_carrier_date: Optional[str],
    items: List[Dict[str, Any]]
) -> Dict[str, bool]:
    """
    Evaluates date comparison flags for late delivery logic.
    """
    dt_delivered = parse_datetime(delivered_customer_date)
    dt_estimated = parse_datetime(estimated_delivery_date)
    dt_carrier = parse_datetime(delivered_carrier_date)

    is_delivered_after_estimate = False
    if dt_delivered and dt_estimated:
        is_delivered_after_estimate = dt_delivered.date() > dt_estimated.date()

    carrier_pickup_after_limit = False
    if dt_carrier and items:
        limit_dts = [parse_datetime(i.get("shipping_limit_date")) for i in items]
        valid_limits = [d for d in limit_dts if d is not None]
        if valid_limits:
            max_limit = max(valid_limits)
            carrier_pickup_after_limit = dt_carrier > max_limit

    return {
        "is_delivered_after_estimate": is_delivered_after_estimate,
        "carrier_pickup_after_limit": carrier_pickup_after_limit,
    }


def evaluate_policy(
    order_status: str,
    payment_total_brl: float,
    item_total_brl: float,
    freight_total_brl: float,
    payment_rows_count: int,
    is_delivered_after_estimate: bool,
    carrier_pickup_after_limit: bool,
    violating_seller_ids: Optional[List[str]] = None,
    delivered_customer_date: Optional[str] = None,
    estimated_delivery_date: Optional[str] = None,
    delivered_carrier_date: Optional[str] = None,
    shipping_limit_dates: Optional[List[str]] = None,
) -> PolicyFinding:
    """
    Evaluates business policy rules EC_POLICY_V1 in strict priority order (1 to 6).
    Confidence is computed dynamically based on data quality and rule match strength.
    """
    order_status_lower = (order_status or "").strip().lower()
    expected_total = item_total_brl + freight_total_brl
    payment_diff = abs(payment_total_brl - expected_total)
    is_payment_reconciled = payment_diff <= (0.10 + 1e-7)

    # --- Confidence helpers ---
    def _payment_confidence() -> float:
        """Higher confidence when payment matches item+freight more closely."""
        if expected_total == 0:
            return 0.90
        if payment_diff < 0.01:
            return 0.98
        elif payment_diff <= 0.05:
            return 0.95
        elif payment_diff <= 0.10:
            return 0.92
        else:
            return 0.85

    def _delivery_late_confidence() -> float:
        """Higher confidence when the delivery is later by more days."""
        dt_deliv = parse_datetime(delivered_customer_date)
        dt_est = parse_datetime(estimated_delivery_date)
        if dt_deliv and dt_est:
            days_late = (dt_deliv.date() - dt_est.date()).days
            if days_late >= 7:
                return 0.97
            elif days_late >= 3:
                return 0.95
            elif days_late >= 1:
                return 0.92
        return 0.90

    def _seller_late_confidence() -> float:
        """Higher confidence when carrier pickup is clearly after shipping limit."""
        dt_carrier = parse_datetime(delivered_carrier_date)
        if dt_carrier and shipping_limit_dates:
            parsed_limits = [parse_datetime(s) for s in shipping_limit_dates if s]
            valid = [d for d in parsed_limits if d]
            if valid:
                latest_limit = max(valid)
                days_over = (dt_carrier.date() - latest_limit.date()).days
                if days_over >= 5:
                    return 0.97
                elif days_over >= 2:
                    return 0.95
                elif days_over >= 1:
                    return 0.92
        return 0.90

    # Priority 1: canceled_order_paid
    if order_status_lower == "canceled" and payment_total_brl > 0:
        refund = round(payment_total_brl, 2)
        return PolicyFinding(
            primary_issue="canceled_order_paid",
            root_cause_code="ORDER_CANCELED_AFTER_PAYMENT",
            responsible_party="platform",
            responsible_party_ids=["OLIST_PLATFORM"],
            recommended_refund_brl=refund,
            resolution_actions=["issue_full_refund"],
            case_status="action_required" if refund > 0 else "no_action",
            evidence_policy_id="policy:ORDER_CANCELED_AFTER_PAYMENT",
            confidence=round(_payment_confidence(), 2),
        )

    # Priority 2: unavailable_order_paid
    if order_status_lower == "unavailable" and payment_total_brl > 0:
        refund = round(payment_total_brl, 2)
        return PolicyFinding(
            primary_issue="unavailable_order_paid",
            root_cause_code="ORDER_UNAVAILABLE_AFTER_PAYMENT",
            responsible_party="platform",
            responsible_party_ids=["OLIST_PLATFORM"],
            recommended_refund_brl=refund,
            resolution_actions=["issue_full_refund"],
            case_status="action_required" if refund > 0 else "no_action",
            evidence_policy_id="policy:ORDER_UNAVAILABLE_AFTER_PAYMENT",
            confidence=round(_payment_confidence(), 2),
        )

    # Priority 3: late_delivery_seller
    if is_delivered_after_estimate and carrier_pickup_after_limit:
        refund = round(freight_total_brl, 2)
        seller_id_list = violating_seller_ids if violating_seller_ids else ["SELLER"]
        return PolicyFinding(
            primary_issue="late_delivery_seller",
            root_cause_code="SELLER_HANDOFF_AFTER_LIMIT",
            responsible_party="seller",
            responsible_party_ids=seller_id_list,
            recommended_refund_brl=refund,
            resolution_actions=["refund_freight"],
            case_status="action_required" if refund > 0 else "no_action",
            evidence_policy_id="policy:SELLER_HANDOFF_AFTER_LIMIT",
            confidence=round(min(_delivery_late_confidence(), _seller_late_confidence()), 2),
        )

    # Priority 4: late_delivery_logistics
    if is_delivered_after_estimate and not carrier_pickup_after_limit:
        refund = round(freight_total_brl, 2)
        return PolicyFinding(
            primary_issue="late_delivery_logistics",
            root_cause_code="CARRIER_DELIVERED_AFTER_ESTIMATE",
            responsible_party="logistics_provider",
            responsible_party_ids=["LOGISTICS_PROVIDER"],
            recommended_refund_brl=refund,
            resolution_actions=["refund_freight"],
            case_status="action_required" if refund > 0 else "no_action",
            evidence_policy_id="policy:CARRIER_DELIVERED_AFTER_ESTIMATE",
            confidence=round(_delivery_late_confidence(), 2),
        )

    # Priority 5: valid_split_payment
    if payment_rows_count >= 2 and is_payment_reconciled:
        return PolicyFinding(
            primary_issue="valid_split_payment",
            root_cause_code="MULTIPLE_PAYMENTS_RECONCILED",
            responsible_party="none",
            responsible_party_ids=[],
            recommended_refund_brl=0.0,
            resolution_actions=["explain_valid_split_payment"],
            case_status="no_action",
            evidence_policy_id="policy:MULTIPLE_PAYMENTS_RECONCILED",
            confidence=round(_payment_confidence(), 2),
        )

    # Priority 6: unsupported_late_claim
    if not is_delivered_after_estimate and is_payment_reconciled:
        return PolicyFinding(
            primary_issue="unsupported_late_claim",
            root_cause_code="DELIVERY_WITHIN_ESTIMATE",
            responsible_party="none",
            responsible_party_ids=[],
            recommended_refund_brl=0.0,
            resolution_actions=["reject_late_refund"],
            case_status="no_action",
            evidence_policy_id="policy:DELIVERY_WITHIN_ESTIMATE",
            confidence=round(_payment_confidence() * 0.97, 2),
        )

    # Fallback Rule: unsupported_claim
    return PolicyFinding(
        primary_issue="unsupported_claim",
        root_cause_code="NO_POLICY_MATCH",
        responsible_party="none",
        responsible_party_ids=[],
        recommended_refund_brl=0.0,
        resolution_actions=["reject_claim"],
        case_status="no_action",
        evidence_policy_id="policy:NO_POLICY_MATCH",
        confidence=0.85,
    )


def generate_evidence_ids(
    order_id: str,
    items: List[Dict[str, Any]],
    payments: List[Dict[str, Any]],
    sellers: List[str],
    root_cause_code: str
) -> List[str]:
    """
    Generates structured evidence IDs adhering strictly to schema rules.
    Maximum 10 items total.
    """
    evidence = [f"order:{order_id}"]

    for item in items[:5]:
        item_seq = item.get("order_item_id", 1)
        evidence.append(f"item:{order_id}:{item_seq}")

    for pay in payments[:5]:
        pay_seq = pay.get("payment_sequential", 1)
        evidence.append(f"payment:{order_id}:{pay_seq}")

    for seller_id in sellers[:5]:
        if seller_id:
            evidence.append(f"seller:{seller_id}")

    evidence.append(f"policy:{root_cause_code}")
    return evidence[:10]


def generate_affected_entities(
    order_id: str,
    items: List[Dict[str, Any]],
    payments: List[Dict[str, Any]],
    sellers: List[str]
) -> Dict[str, List[str]]:
    """
    Generates affected_entities mapping with strict array length caps and empty array rules.
    """
    order_ids = [order_id] if order_id else []

    if items:
        item_ids = [f"{order_id}:{i.get('order_item_id', 1)}" for i in items[:5]]
        seller_ids = list(dict.fromkeys([s for s in sellers if s]))[:5]
    else:
        item_ids = []
        seller_ids = []

    if payments:
        payment_ids = [f"{order_id}:{p.get('payment_sequential', 1)}" for p in payments[:5]]
    else:
        payment_ids = []

    return {
        "order_ids": order_ids,
        "item_ids": item_ids,
        "seller_ids": seller_ids,
        "payment_ids": payment_ids,
    }
