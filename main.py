"""
main.py

Primary entrypoint for the Olist E-Commerce Dispute Resolution Multi-Agent System.
Imports and executes run_pipeline.py main function, propagating standard OS exit codes (0 for success, 1 for failure).
"""

import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv

load_dotenv()

from run_pipeline import main as run_pipeline_main

if __name__ == "__main__":
    exit_code = run_pipeline_main()
    sys.exit(exit_code)
