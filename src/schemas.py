"""
src/schemas.py

Pydantic v2 schemas for multi-agent dispute resolution outputs and LangGraph state types.
Adheres strictly to Requirement R3 and EC_POLICY_V1 specifications.
"""

import re
import operator
from typing import List, Literal, Optional, Dict, Any, Annotated
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from typing_extensions import TypedDict

# =============================================================================
# Regex Patterns & Constants
# =============================================================================

# Evidence ID format: order:<id>, item:<oid>:<item_id>, payment:<oid>:<seq>, seller:<sid>, policy:<code>
EVIDENCE_REGEX = re.compile(
    r"^(order:[^:]+|item:[^:]+:\d+|payment:[^:]+:\d+|seller:[^:]+|policy:[A-Z0-9_]+)$"
)

# Valid Primary Issues per EC_POLICY_V1
PRIMARY_ISSUES = Literal[
    'canceled_order_paid',
    'unavailable_order_paid',
    'late_delivery_seller',
    'late_delivery_logistics',
    'valid_split_payment',
    'unsupported_late_claim',
    'unsupported_claim'
]

# Valid Case Statuses
CASE_STATUSES = Literal['action_required', 'no_action']

# Valid Root Cause Codes
CAUSE_CODES = Literal[
    'SELLER_HANDOFF_AFTER_LIMIT',
    'CARRIER_DELIVERED_AFTER_ESTIMATE',
    'ORDER_CANCELED_AFTER_PAYMENT',
    'ORDER_UNAVAILABLE_AFTER_PAYMENT',
    'MULTIPLE_PAYMENTS_RECONCILED',
    'DELIVERY_WITHIN_ESTIMATE',
    'NO_POLICY_MATCH'
]

# Valid Resolution Actions
RESOLUTION_ACTIONS = Literal[
    'issue_full_refund',
    'refund_freight',
    'explain_valid_split_payment',
    'reject_late_refund',
    'reject_claim'
]


# =============================================================================
# 1. Assessment Model
# =============================================================================

class Assessment(BaseModel):
    """
    Primary issue, case status, and agent confidence score.
    """
    model_config = ConfigDict(extra='forbid')

    primary_issue: PRIMARY_ISSUES = Field(
        ...,
        description="Categorized issue type matching EC_POLICY_V1"
    )
    case_status: CASE_STATUSES = Field(
        ...,
        description="'action_required' if refund > 0, else 'no_action'"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0.0 and 1.0"
    )

    @field_validator('confidence', mode='before')
    @classmethod
    def round_confidence(cls, v: float) -> float:
        if isinstance(v, (int, float)):
            return round(float(v), 2)
        return v


# =============================================================================
# 2. Affected Entities Model
# =============================================================================

class AffectedEntities(BaseModel):
    """
    Identified entities associated with the dispute. Max 5 IDs per list.
    """
    model_config = ConfigDict(extra='forbid')

    order_ids: List[str] = Field(default_factory=list, max_length=5, description="List of order IDs")
    item_ids: List[str] = Field(default_factory=list, max_length=5, description="List of item IDs (format: <order_id>:<item_id>)")
    seller_ids: List[str] = Field(default_factory=list, max_length=5, description="List of seller IDs")
    payment_ids: List[str] = Field(default_factory=list, max_length=5, description="List of payment IDs (format: <order_id>:<seq>)")


# =============================================================================
# 3. Root Cause Analysis Models
# =============================================================================

class RankedCause(BaseModel):
    """
    Ranked root cause code and numerical rank.
    """
    model_config = ConfigDict(extra='forbid')

    cause_code: CAUSE_CODES = Field(..., description="Standardized root cause code")
    rank: int = Field(..., ge=1, description="Rank priority, starting at 1")


class ResponsibleParty(BaseModel):
    """
    Identified responsible party and identifier.
    """
    model_config = ConfigDict(extra='forbid')

    party_type: str = Field(..., description="Type of party (seller, platform, logistics_provider, none)")
    party_id: str = Field(..., description="ID of responsible seller or entity keyword (OLIST_PLATFORM, LOGISTICS_PROVIDER, NONE)")


class RootCauseAnalysis(BaseModel):
    """
    Root cause breakdown. Max 3 causes and 3 responsible parties.
    """
    model_config = ConfigDict(extra='forbid')

    ranked_causes: List[RankedCause] = Field(default_factory=list, max_length=3, description="Ranked cause list (max 3)")
    responsible_parties: List[ResponsibleParty] = Field(default_factory=list, max_length=3, description="Responsible parties (max 3)")


# =============================================================================
# 4. Financial Resolution Model
# =============================================================================

class FinancialResolution(BaseModel):
    """
    Financial breakdown and recommended refund in BRL, rounded to 2 decimal places.
    """
    model_config = ConfigDict(extra='forbid')

    currency: Literal['BRL'] = Field(default='BRL', description="Currency code (always BRL)")
    item_total_brl: float = Field(..., ge=0.0, description="Sum of item prices")
    freight_total_brl: float = Field(..., ge=0.0, description="Sum of freight charges")
    payment_total_brl: float = Field(..., ge=0.0, description="Sum of payment values")
    recommended_refund_brl: float = Field(..., ge=0.0, description="Calculated refund amount in BRL")

    @field_validator('item_total_brl', 'freight_total_brl', 'payment_total_brl', 'recommended_refund_brl', mode='before')
    @classmethod
    def round_to_two_decimals(cls, v: float) -> float:
        if isinstance(v, (int, float)):
            return round(float(v), 2)
        return v


# =============================================================================
# 5. Root Output Container (DisputeOutput)
# =============================================================================

class DisputeOutput(BaseModel):
    """
    Top-level output schema for resolved e-commerce disputes (R3 compliant).
    """
    model_config = ConfigDict(extra='forbid')

    case_id: str = Field(..., description="Case ID (e.g. EC_001)")
    assessment: Assessment
    affected_entities: AffectedEntities
    root_cause_analysis: RootCauseAnalysis
    evidence_ids: List[str] = Field(..., max_length=10, description="List of evidence IDs (max 10)")
    financial_resolution: FinancialResolution
    resolution_actions: List[str] = Field(..., max_length=5, description="Action strings (max 5)")

    @field_validator('evidence_ids')
    @classmethod
    def validate_evidence_id_formats(cls, v: List[str]) -> List[str]:
        """
        Ensures each evidence ID follows regex patterns:
        - order:<id>
        - item:<oid>:<item_id>
        - payment:<oid>:<seq>
        - seller:<sid>
        - policy:<code>
        """
        for evid in v:
            if not EVIDENCE_REGEX.match(evid):
                raise ValueError(
                    f"Invalid evidence ID format: '{evid}'. Must match pattern order:<id>, item:<oid>:<item_id>, payment:<oid>:<seq>, seller:<sid>, or policy:<code>."
                )
        return v

    @model_validator(mode='after')
    def validate_cross_field_business_rules(self) -> 'DisputeOutput':
        """
        Validates business rule consistency:
        - case_status must be 'action_required' if recommended_refund_brl > 0
        - case_status must be 'no_action' if recommended_refund_brl == 0
        """
        refund = self.financial_resolution.recommended_refund_brl
        status = self.assessment.case_status
        if refund > 0.0 and status != 'action_required':
            raise ValueError(f"Inconsistency: recommended_refund_brl={refund} > 0 but case_status='{status}'. Must be 'action_required'.")
        elif refund == 0.0 and status != 'no_action':
            raise ValueError(f"Inconsistency: recommended_refund_brl={refund} == 0 but case_status='{status}'. Must be 'no_action'.")
        return self


# =============================================================================
# 6. LangGraph State Type (DisputeState)
# =============================================================================

class DisputeState(TypedDict, total=False):
    """
    LangGraph State Schema for 6-Agent Pipeline execution.
    """
    case_id: str
    input_data: Dict[str, Any]
    order_info: Optional[Dict[str, Any]]
    payment_info: Optional[Dict[str, Any]]
    delivery_info: Optional[Dict[str, Any]]
    policy_finding: Optional[Dict[str, Any]]
    final_output: Optional[Dict[str, Any]]
    trace_steps: Annotated[List[Dict[str, Any]], operator.add]
    errors: Annotated[List[str], operator.add]
