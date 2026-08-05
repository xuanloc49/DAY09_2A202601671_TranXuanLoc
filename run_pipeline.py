"""
run_pipeline.py

Batch Processing Engine for Milestone 3.
Processes EC_001.json through EC_050.json from input/ to output/.
"""

import os
import re
import sys
import json
import time
import argparse
import logging
from typing import List, Dict, Any

from src.graph import run_dispute_pipeline
from src.logger import ExecutionLogger

from dotenv import load_dotenv

load_dotenv()

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_pipeline")


def extract_case_number(filename: str) -> int:
    """Extracts integer suffix from case filename (e.g., EC_005.json -> 5)."""
    match = re.search(r"EC_(\d+)", filename, re.IGNORECASE)
    return int(match.group(1)) if match else 999999


def parse_args(args_list: List[str] = None):
    parser = argparse.ArgumentParser(
        description="Run Olist E-Commerce Dispute Resolution Pipeline in Batch Mode."
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default=os.getenv("INPUT_DIR", "input"),
        help="Path to input directory containing case JSON files (default: input)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=os.getenv("OUTPUT_DIR", "output"),
        help="Path to output directory for resolved case JSON files (default: output)",
    )
    parser.add_argument(
        "--case-id",
        type=str,
        default=None,
        help="Process a single case ID (e.g. EC_001)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of cases to process",
    )
    parser.add_argument(
        "--clear-trace",
        action="store_true",
        help="Clear existing logging/trace.jsonl before starting run",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output logging",
    )
    if args_list is not None:
        return parser.parse_args(args_list)
    return parser.parse_args()


def main(args_list: List[str] = None) -> int:
    """
    Main batch processing execution loop.
    Returns:
        0 on success (0 case failures)
        1 on failure (1 or more case failures or invalid inputs)
    """
    args = parse_args(args_list)
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_dir = os.path.abspath(args.input_dir) if os.path.isabs(args.input_dir) else os.path.abspath(os.path.join(base_dir, args.input_dir))
    output_dir = os.path.abspath(args.output_dir) if os.path.isabs(args.output_dir) else os.path.abspath(os.path.join(base_dir, args.output_dir))
    log_dir = os.path.join(base_dir, "logging")

    # 1. Directory creation
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    exec_logger = ExecutionLogger(log_dir=log_dir)
    if args.clear_trace:
        logger.info("Clearing existing trace log...")
        exec_logger.clear_trace()

    # 2. Case Discovery
    if not os.path.exists(input_dir):
        logger.error(f"Input directory not found: {input_dir}")
        return 1

    all_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".json")]
    all_files.sort(key=extract_case_number)

    # 3. Filtering
    if args.case_id:
        raw_id = args.case_id.strip()
        if raw_id.isdigit():
            target_id = f"EC_{int(raw_id):03d}"
        elif not raw_id.upper().startswith("EC_"):
            target_id = f"EC_{raw_id.upper()}"
        else:
            target_id = raw_id.upper()

        all_files = [f for f in all_files if f.replace('.json', '').replace('.JSON', '').upper() == target_id]
        if not all_files:
            logger.error(f"No case file found matching case-id '{args.case_id}' in {input_dir}")
            return 1

    if args.limit is not None:
        if args.limit < 0:
            logger.error(f"Invalid limit parameter: {args.limit}. Must be >= 0.")
            return 1
        all_files = all_files[:args.limit]

    total_cases = len(all_files)
    logger.info(f"Starting batch execution for {total_cases} case(s)...")

    successful_count = 0
    failed_count = 0
    start_time = time.perf_counter()

    # 4. Processing Loop
    for idx, fname in enumerate(all_files, start=1):
        in_file_path = os.path.join(input_dir, fname)
        out_file_path = os.path.join(output_dir, fname)

        logger.info(f"[{idx}/{total_cases}] Processing {fname}...")
        case_start = time.perf_counter()

        try:
            with open(in_file_path, "r", encoding="utf-8") as f:
                case_data = json.load(f)

            # Invoke dispute resolution graph
            result_dict = run_dispute_pipeline(case_data)

            if not result_dict:
                raise ValueError(f"Pipeline returned empty result for {fname}")

            # Write formatted output JSON with 2-space indentation
            with open(out_file_path, "w", encoding="utf-8") as f:
                json.dump(result_dict, f, indent=2, ensure_ascii=False)

            case_ms = (time.perf_counter() - case_start) * 1000.0
            logger.info(f"Successfully processed {fname} in {case_ms:.1f} ms -> {out_file_path}")
            successful_count += 1

        except Exception as e:
            case_ms = (time.perf_counter() - case_start) * 1000.0
            logger.error(f"Error processing {fname} after {case_ms:.1f} ms: {e}", exc_info=True)
            failed_count += 1

    total_elapsed_sec = time.perf_counter() - start_time
    avg_latency_ms = (total_elapsed_sec * 1000.0 / total_cases) if total_cases > 0 else 0.0

    # 5. Metadata Generation
    exec_logger.generate_metadata(total_cases_processed=successful_count)

    # 6. Summary Report
    print("\n" + "=" * 60)
    print(" BATCH EXECUTION SUMMARY ")
    print("=" * 60)
    print(f" Total Cases Attempted  : {total_cases}")
    print(f" Successfully Processed : {successful_count}")
    print(f" Failed Cases           : {failed_count}")
    print(f" Total Execution Time   : {total_elapsed_sec:.2f} seconds")
    print(f" Average Latency / Case : {avg_latency_ms:.1f} ms")
    print(f" Output Directory       : {output_dir}")
    print(f" Metadata Generated     : {os.path.join(log_dir, 'metadata.json')}")
    print("=" * 60 + "\n")

    if failed_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
