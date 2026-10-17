#!/usr/bin/env python3
"""Autonomous FinOps Cloud & Container Cost Analyzer CLI and HTTP Microservice."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from finops_service.analyzer import (
    SKU_CATALOG,
    USD_TO_RUB_RATE,
    FinOpsAnalyzer,
    FinOpsAuditStore,
    RightsizingRecommendation,
    analyze_nat_egress,
    get_perfops_estate_preset,
)
from finops_service.server import SERVICE_VERSION, create_server, run_server

__all__ = [
    "SKU_CATALOG",
    "USD_TO_RUB_RATE",
    "FinOpsAnalyzer",
    "FinOpsAuditStore",
    "RightsizingRecommendation",
    "analyze_nat_egress",
    "create_server",
    "get_perfops_estate_preset",
    "main",
    "run_server",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finops_agent",
        description="Autonomous FinOps cloud, VPS, Docker cgroup, and LLM cost analyzer.",
    )
    parser.add_argument("--version", action="version", version=f"finops-cost-agent {SERVICE_VERSION}")
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Start the FinOps HTTP microservice")
    serve_p.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    serve_p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "4030")))
    serve_p.add_argument("--db", default=os.environ.get("FINOPS_DB_PATH", "finops_audit.db"))

    audit_p = sub.add_parser("audit", help="Run a FinOps audit from preset or JSON file")
    audit_p.add_argument("--preset", choices=["perfops-estate"], default="perfops-estate")
    audit_p.add_argument("--input", help="Path to custom workload JSON payload")
    audit_p.add_argument("--db", default=os.environ.get("FINOPS_DB_PATH", "finops_audit.db"))

    sub.add_parser("catalog", help="Print the cloud, VPS, and LLM pricing catalog as JSON")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        run_server(host=args.host, port=args.port, db_path=args.db)
        return 0

    if args.command == "catalog":
        print(json.dumps(SKU_CATALOG, indent=2))
        return 0

    # Default or "audit" command runs the estate analysis
    db_path = getattr(args, "db", os.environ.get("FINOPS_DB_PATH", ":memory:"))
    analyzer = FinOpsAnalyzer(store=FinOpsAuditStore(db_path))
    input_file = getattr(args, "input", None)
    if input_file:
        with open(input_file, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        preset_name = "custom-file"
    else:
        payload = get_perfops_estate_preset()
        preset_name = "perfops-estate"

    report = analyzer.analyze_estate(payload, persist=True, preset_name=preset_name)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
