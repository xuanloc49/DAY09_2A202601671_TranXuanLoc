"""
src/tools.py

Data layer utilities and LangChain tools for querying the Olist CSV dataset.
Includes Singleton OlistDataManager, 4 @tool functions, and deterministic calculation helpers.
"""

import os
import pandas as pd
from typing import Dict, List, Any, Optional
from datetime import datetime
from langchain_core.tools import tool

# Path to dataset directory relative to this file
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _clean_dict(d: dict) -> dict:
    """Replaces NaNs or null values with None for clean JSON serialization."""
    cleaned = {}
    for k, v in d.items():
        if pd.isna(v):
            cleaned[k] = None
        else:
            cleaned[k] = v
    return cleaned


class OlistDataManager:
    """
    Singleton DataManager to load and index Olist CSV datasets into memory for O(1) lookups.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(OlistDataManager, cls).__new__(cls)
            cls._instance._load_data()
        return cls._instance

    def _load_data(self):
        orders_path = os.path.join(DATA_DIR, "olist_orders_dataset.csv")
        items_path = os.path.join(DATA_DIR, "olist_order_items_dataset.csv")
        payments_path = os.path.join(DATA_DIR, "olist_order_payments_dataset.csv")
        sellers_path = os.path.join(DATA_DIR, "olist_sellers_dataset.csv")
        customers_path = os.path.join(DATA_DIR, "olist_customers_dataset.csv")

        orders_df = pd.read_csv(orders_path)
        items_df = pd.read_csv(items_path)
        payments_df = pd.read_csv(payments_path)
        sellers_df = pd.read_csv(sellers_path)
        customers_df = pd.read_csv(customers_path)

        # Index orders by order_id
        self.orders_by_id: Dict[str, dict] = {}
        for row in orders_df.to_dict(orient="records"):
            cleaned = _clean_dict(row)
            self.orders_by_id[str(cleaned["order_id"])] = cleaned

        # Group items by order_id
        self.items_by_order: Dict[str, List[dict]] = {}
        for row in items_df.to_dict(orient="records"):
            cleaned = _clean_dict(row)
            oid = str(cleaned["order_id"])
            if oid not in self.items_by_order:
                self.items_by_order[oid] = []
            self.items_by_order[oid].append(cleaned)

        # Group payments by order_id
        self.payments_by_order: Dict[str, List[dict]] = {}
        for row in payments_df.to_dict(orient="records"):
            cleaned = _clean_dict(row)
            oid = str(cleaned["order_id"])
            if oid not in self.payments_by_order:
                self.payments_by_order[oid] = []
            self.payments_by_order[oid].append(cleaned)

        # Index sellers by seller_id
        self.sellers_by_id: Dict[str, dict] = {}
        for row in sellers_df.to_dict(orient="records"):
            cleaned = _clean_dict(row)
            self.sellers_by_id[str(cleaned["seller_id"])] = cleaned

        # Index customers by customer_id
        self.customers_by_id: Dict[str, dict] = {}
        for row in customers_df.to_dict(orient="records"):
            cleaned = _clean_dict(row)
            self.customers_by_id[str(cleaned["customer_id"])] = cleaned


@tool
def get_order_details(order_id: str) -> dict:
    """
    Retrieve order status and delivery dates for a given order_id.

    Args:
        order_id: The unique identifier of the order (32-char hex string).

    Returns:
        Dict containing order_status, purchase timestamp, approved timestamp,
        delivered_carrier_date, delivered_customer_date, estimated_delivery_date,
        and evidence_id ('order:<order_id>').
    """
    data_mgr = OlistDataManager()
    order = data_mgr.orders_by_id.get(order_id)
    if not order:
        return {
            "found": False,
            "order_id": order_id,
            "error": f"Order {order_id} not found in database."
        }

    return {
        "found": True,
        "order_id": order_id,
        "customer_id": str(order["customer_id"]),
        "order_status": str(order["order_status"]),
        "order_purchase_timestamp": order.get("order_purchase_timestamp"),
        "order_approved_at": order.get("order_approved_at"),
        "order_delivered_carrier_date": order.get("order_delivered_carrier_date"),
        "order_delivered_customer_date": order.get("order_delivered_customer_date"),
        "order_estimated_delivery_date": order.get("order_estimated_delivery_date"),
        "evidence_id": f"order:{order_id}"
    }


@tool
def get_order_items(order_id: str) -> dict:
    """
    Retrieve item line items, prices, seller IDs, shipping limit dates, and total financial amounts for an order.

    Args:
        order_id: The unique identifier of the order.

    Returns:
        Dict containing item list, item_count, item_total_brl, freight_total_brl,
        seller_ids list, item_entity_ids, and item_evidence_ids.
    """
    data_mgr = OlistDataManager()
    items = data_mgr.items_by_order.get(order_id, [])

    formatted_items = []
    item_total = 0.0
    freight_total = 0.0
    seller_ids = set()
    item_evidence_ids = []
    item_entity_ids = []

    for item in items:
        price = round(float(item["price"]), 2) if item.get("price") is not None else 0.0
        freight = round(float(item["freight_value"]), 2) if item.get("freight_value") is not None else 0.0
        item_id = int(item["order_item_id"])
        seller_id = str(item["seller_id"])

        item_str = f"{order_id}:{item_id}"
        item_entity_ids.append(item_str)
        item_evidence_ids.append(f"item:{item_str}")
        seller_ids.add(seller_id)

        item_total += price
        freight_total += freight

        formatted_items.append({
            "order_id": order_id,
            "order_item_id": item_id,
            "product_id": str(item["product_id"]),
            "seller_id": seller_id,
            "shipping_limit_date": item.get("shipping_limit_date"),
            "price_brl": price,
            "freight_value_brl": freight,
            "evidence_id": f"item:{item_str}"
        })

    return {
        "order_id": order_id,
        "items": formatted_items,
        "item_count": len(formatted_items),
        "item_total_brl": round(item_total, 2),
        "freight_total_brl": round(freight_total, 2),
        "seller_ids": list(seller_ids),
        "item_entity_ids": item_entity_ids,
        "item_evidence_ids": item_evidence_ids
    }


@tool
def get_order_payments(order_id: str) -> dict:
    """
    Retrieve payment breakdown, payment types, installments, and payment total for an order.

    Args:
        order_id: The unique identifier of the order.

    Returns:
        Dict containing payment list, payment_count, payment_total_brl,
        payment_entity_ids, and payment_evidence_ids.
    """
    data_mgr = OlistDataManager()
    payments = data_mgr.payments_by_order.get(order_id, [])

    formatted_payments = []
    payment_total = 0.0
    payment_evidence_ids = []
    payment_entity_ids = []

    for pay in payments:
        seq = int(pay["payment_sequential"])
        val = round(float(pay["payment_value"]), 2) if pay.get("payment_value") is not None else 0.0

        pay_str = f"{order_id}:{seq}"
        payment_entity_ids.append(pay_str)
        payment_evidence_ids.append(f"payment:{pay_str}")

        payment_total += val

        formatted_payments.append({
            "order_id": order_id,
            "payment_sequential": seq,
            "payment_type": str(pay["payment_type"]),
            "payment_installments": int(pay["payment_installments"]),
            "payment_value_brl": val,
            "evidence_id": f"payment:{pay_str}"
        })

    return {
        "order_id": order_id,
        "payments": formatted_payments,
        "payment_count": len(formatted_payments),
        "payment_total_brl": round(payment_total, 2),
        "payment_entity_ids": payment_entity_ids,
        "payment_evidence_ids": payment_evidence_ids
    }


@tool
def get_seller_details(seller_id: str) -> dict:
    """
    Retrieve seller location metadata by seller_id.

    Args:
        seller_id: The unique identifier of the seller.

    Returns:
        Dict containing seller_id, zip code, city, state, evidence_id ('seller:<seller_id>').
    """
    data_mgr = OlistDataManager()
    seller = data_mgr.sellers_by_id.get(seller_id)
    if not seller:
        return {
            "found": False,
            "seller_id": seller_id,
            "error": f"Seller {seller_id} not found."
        }

    return {
        "found": True,
        "seller_id": seller_id,
        "seller_zip_code_prefix": str(seller["seller_zip_code_prefix"]),
        "seller_city": str(seller["seller_city"]),
        "seller_state": str(seller["seller_state"]),
        "evidence_id": f"seller:{seller_id}"
    }


def parse_olist_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """Parse Olist timestamp string into datetime object."""
    if not ts_str or pd.isna(ts_str) or ts_str == "None":
        return None
    ts_clean = str(ts_str).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts_clean[:19], fmt[:19] if len(ts_clean) >= 19 else fmt)
        except ValueError:
            continue
    return None


def check_delivery_lateness(
    delivered_customer_date: Optional[str],
    estimated_delivery_date: Optional[str]
) -> Optional[bool]:
    """
    Returns True if delivered_customer_date is AFTER estimated_delivery_date (date-only comparison).
    The estimated_delivery_date in Olist always has time 00:00:00, so we compare
    only the date portion to avoid false positives for same-day deliveries.
    Returns None if either date is missing.
    """
    deliv_dt = parse_olist_timestamp(delivered_customer_date)
    est_dt = parse_olist_timestamp(estimated_delivery_date)

    if deliv_dt is None or est_dt is None:
        return None

    return deliv_dt.date() > est_dt.date()


def check_carrier_pickup_lateness(
    delivered_carrier_date: Optional[str],
    shipping_limit_date: Optional[str]
) -> Optional[bool]:
    """
    Returns True if delivered_carrier_date > shipping_limit_date.
    Returns None if delivered_carrier_date or shipping_limit_date is missing.
    """
    carrier_dt = parse_olist_timestamp(delivered_carrier_date)
    limit_dt = parse_olist_timestamp(shipping_limit_date)

    if carrier_dt is None or limit_dt is None:
        return None

    return carrier_dt > limit_dt


def reconcile_financials(
    payment_total: float,
    item_total: float,
    freight_total: float,
    tolerance: float = 0.10
) -> bool:
    """
    Checks if payment_total matches (item_total + freight_total) within tolerance (default 0.10 BRL).
    """
    expected_total = round(item_total + freight_total, 2)
    actual_total = round(payment_total, 2)
    return abs(actual_total - expected_total) <= (tolerance + 1e-9)
