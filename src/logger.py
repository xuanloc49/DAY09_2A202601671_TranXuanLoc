"""
src/logger.py

Execution Tracing & System Metadata Logger for Milestone 2.
Provides thread-safe real-time logging to `logging/trace.jsonl` and metadata generation to `logging/metadata.json`.
"""

import os
import json
import time
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Literal, Generator
from pydantic import BaseModel, Field, ConfigDict

# Base directory paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logging")
TRACE_FILE = os.path.join(LOG_DIR, "trace.jsonl")
METADATA_FILE = os.path.join(LOG_DIR, "metadata.json")

VALID_AGENTS = Literal[
    "Coordinator",
    "OrderSellerAgent",
    "PaymentAgent",
    "DeliveryAgent",
    "PolicyAgent",
    "VerifierAgent",
    "coordinator_agent",
    "order_seller_agent",
    "payment_agent",
    "delivery_agent",
    "policy_agent",
    "verifier_agent"
]

VALID_STATUSES = Literal["SUCCESS", "WARNING", "ERROR"]


class TraceEntry(BaseModel):
    """Schema for individual execution trace steps stored in trace.jsonl."""
    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(..., description="ISO 8601 timestamp string")
    case_id: str = Field(..., description="Case identifier e.g. EC_001")
    agent_name: VALID_AGENTS = Field(..., description="Name of the agent executing the step")
    action: str = Field(..., description="Description of action or tool executed")
    input_summary: Dict[str, Any] = Field(default_factory=dict, description="Summary of input arguments or state")
    output_summary: Dict[str, Any] = Field(default_factory=dict, description="Summary of agent output or state updates")
    status: VALID_STATUSES = Field(default="SUCCESS", description="Execution status")
    latency_ms: float = Field(..., ge=0.0, description="Execution duration in milliseconds")


class MetadataEntry(BaseModel):
    """Schema for system metadata stored in metadata.json."""
    model_config = ConfigDict(extra="forbid")

    model: str = Field(default="llama-3.1-8b-instant", description="Groq LLM model name")
    parameters: str = Field(default="8B", description="Model parameter size count")
    framework: str = Field(default="LangChain / LangGraph", description="Agent framework used")
    system_name: str = Field(
        default="Olist E-Commerce Dispute Resolution Multi-Agent System",
        description="System title"
    )
    execution_timestamp: str = Field(..., description="ISO 8601 timestamp of execution completion")
    total_cases_processed: int = Field(..., ge=0, description="Total number of cases processed in batch")
    version: str = Field(default="1.0.0", description="System release version")
    author: str = Field(
        default="Tran Xuan Loc (MSSV: 2A202601671)",
        description="Author / student identification"
    )


class ExecutionLogger:
    """
    Thread-safe Execution Logger for recording real-time trace events to trace.jsonl
    and writing metadata summaries to metadata.json.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, log_dir: str = LOG_DIR):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ExecutionLogger, cls).__new__(cls)
                cls._instance.log_dir = log_dir
                cls._instance.trace_file = os.path.join(log_dir, "trace.jsonl")
                cls._instance.metadata_file = os.path.join(log_dir, "metadata.json")
                os.makedirs(log_dir, exist_ok=True)
            return cls._instance

    def log_step(
        self,
        case_id: str,
        agent_name: str,
        action: str,
        input_summary: Dict[str, Any],
        output_summary: Dict[str, Any],
        status: str = "SUCCESS",
        latency_ms: float = 0.0,
        ts_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Appends a validated trace step entry to logging/trace.jsonl.
        Returns the step dictionary for state accumulation in LangGraph.
        """
        if ts_str is None:
            ts_str = datetime.now(timezone.utc).isoformat()

        entry = TraceEntry(
            timestamp=ts_str,
            case_id=case_id,
            agent_name=agent_name,  # type: ignore
            action=action,
            input_summary=input_summary,
            output_summary=output_summary,
            status=status,  # type: ignore
            latency_ms=round(latency_ms, 2)
        )
        record_dict = entry.model_dump()
        line = json.dumps(record_dict, ensure_ascii=False) + "\n"

        with self._lock:
            os.makedirs(os.path.dirname(self.trace_file), exist_ok=True)
            with open(self.trace_file, "a", encoding="utf-8") as f:
                f.write(line)

        return record_dict

    def generate_metadata(
        self,
        total_cases_processed: int,
        execution_timestamp: Optional[str] = None,
        model: str = "llama-3.1-8b-instant",
        parameters: str = "8B",
        framework: str = "LangChain / LangGraph",
        system_name: str = "Olist E-Commerce Dispute Resolution Multi-Agent System",
        version: str = "1.0.0",
        author: str = "Tran Xuan Loc (MSSV: 2A202601671)"
    ) -> Dict[str, Any]:
        """
        Generates and writes system metadata to logging/metadata.json.
        """
        if execution_timestamp is None:
            execution_timestamp = datetime.now(timezone.utc).isoformat()

        meta = MetadataEntry(
            model=model,
            parameters=parameters,
            framework=framework,
            system_name=system_name,
            execution_timestamp=execution_timestamp,
            total_cases_processed=total_cases_processed,
            version=version,
            author=author
        )
        meta_dict = meta.model_dump()

        with self._lock:
            os.makedirs(os.path.dirname(self.metadata_file), exist_ok=True)
            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(meta_dict, f, indent=2, ensure_ascii=False)

        return meta_dict

    def clear_trace(self):
        """Helper to clear existing trace file (useful for fresh batch runs)."""
        with self._lock:
            if os.path.exists(self.trace_file):
                open(self.trace_file, "w", encoding="utf-8").close()


@contextmanager
def measure_latency() -> Generator[Dict[str, float], None, None]:
    """
    Context manager to measure code block execution latency in milliseconds.

    Usage:
        elapsed = {}
        with measure_latency() as elapsed:
            # execute agent logic
        latency_ms = elapsed["ms"]
    """
    start = time.perf_counter()
    elapsed_dict = {"ms": 0.0}
    try:
        yield elapsed_dict
    finally:
        elapsed_dict["ms"] = (time.perf_counter() - start) * 1000.0
