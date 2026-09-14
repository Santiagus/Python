#!/usr/bin/env python3
"""Automated concurrency benchmark harness comparing sequential vs. parallel execution.

Measures wall-clock latency across financial document underwriting workloads:
1. Sequential Baseline: Step-by-step execution (validation -> KYC -> Tax -> Page-by-page -> Aggregation).
2. Parallel Celery Canvas: Stage 1 validation -> Stage 2 chord fan-out (group of pages + KYC + Tax) -> Stage 3 fan-in aggregation callback.

Outputs Markdown timing tables and JSON metrics for 4-page and 16-page dossiers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from celery import chord
from services.worker.celery_app import celery_app
from services.worker.tasks import (
    aggregate_underwriting_decision,
    process_bank_statement_page,
    process_kyc_document,
    process_tax_return,
    validate_dossier,
)


def get_dossier_manifests() -> dict[str, dict[str, str]]:
    """Resolve file paths for benchmark dossiers."""
    fixtures_dir = PROJECT_ROOT / "tests" / "fixtures"
    clean_dir = fixtures_dir / "clean_4pages"
    benchmark_dir = fixtures_dir / "benchmark_16pages"

    manifests = {
        "4_pages_clean": {
            "bank_statement": str(clean_dir / "bank_statement_4pages.pdf"),
            "kyc_id": str(clean_dir / "kyc_executive_id.jpg"),
            "tax_filing": str(clean_dir / "tax_filing_irs1120.pdf"),
        },
        "16_pages_benchmark": {
            "bank_statement": str(benchmark_dir / "bank_statement_16pages.pdf"),
            "kyc_id": str(clean_dir / "kyc_executive_id.jpg"),
            "tax_filing": str(clean_dir / "tax_filing_irs1120.pdf"),
        },
    }
    return manifests


def run_sequential(
    manifest: dict[str, str],
    applicant_name: str = "JANE DOE",
    requested_facility: Decimal = Decimal("250000.00"),
) -> dict[str, Any]:
    """Execute all pipeline stages in strict sequential order without concurrency."""
    app_id = str(uuid4())
    t0 = time.perf_counter()

    # Step 1: Validate dossier
    t_val_start = time.perf_counter()
    val_res = validate_dossier.apply(
        args=[app_id, manifest, applicant_name, requested_facility]
    ).get()
    t_val_end = time.perf_counter()
    val_duration_ms = (t_val_end - t_val_start) * 1000

    page_ids: list[str] = val_res["page_ids"]

    # Step 2: Sequential document and page processing
    page_results: list[dict[str, Any]] = []

    # Process KYC
    t_kyc_start = time.perf_counter()
    kyc_res = process_kyc_document.apply(
        args=[app_id, manifest["kyc_id"], applicant_name]
    ).get()
    t_kyc_end = time.perf_counter()
    page_results.append(kyc_res)

    # Process Tax
    t_tax_start = time.perf_counter()
    tax_res = process_tax_return.apply(
        args=[app_id, manifest["tax_filing"]]
    ).get()
    t_tax_end = time.perf_counter()
    page_results.append(tax_res)

    # Process statement pages sequentially
    t_pages_start = time.perf_counter()
    for pnum, pid in enumerate(page_ids, start=1):
        stmt_res = process_bank_statement_page.apply(
            args=[app_id, pid, pnum, manifest["bank_statement"]]
        ).get()
        page_results.append(stmt_res)
    t_pages_end = time.perf_counter()

    # Step 3: Aggregate underwriting decision
    t_agg_start = time.perf_counter()
    decision = aggregate_underwriting_decision.apply(
        args=[page_results, app_id, requested_facility]
    ).get()
    t_agg_end = time.perf_counter()

    total_duration_ms = (time.perf_counter() - t0) * 1000

    return {
        "mode": "sequential",
        "application_id": app_id,
        "page_count": len(page_ids),
        "total_tasks": len(page_ids) + 2,
        "total_duration_ms": round(total_duration_ms, 2),
        "validation_duration_ms": round(val_duration_ms, 2),
        "kyc_duration_ms": round((t_kyc_end - t_kyc_start) * 1000, 2),
        "tax_duration_ms": round((t_tax_end - t_tax_start) * 1000, 2),
        "pages_duration_ms": round((t_pages_end - t_pages_start) * 1000, 2),
        "aggregation_duration_ms": round((t_agg_end - t_agg_start) * 1000, 2),
        "decision": decision.get("decision"),
    }


def run_parallel(
    manifest: dict[str, str],
    applicant_name: str = "JANE DOE",
    requested_facility: Decimal = Decimal("250000.00"),
) -> dict[str, Any]:
    """Execute pipeline via Celery Canvas chord (fan-out parallel header -> fan-in callback)."""
    app_id = str(uuid4())
    t0 = time.perf_counter()

    # Stage 1: Validate dossier
    t_val_start = time.perf_counter()
    val_res = validate_dossier.apply(
        args=[app_id, manifest, applicant_name, requested_facility]
    ).get()
    t_val_end = time.perf_counter()
    val_duration_ms = (t_val_end - t_val_start) * 1000

    page_ids: list[str] = val_res["page_ids"]

    # Stage 2: Fan-out parallel chord header
    header = [
        process_kyc_document.s(app_id, manifest["kyc_id"], applicant_name),
        process_tax_return.s(app_id, manifest["tax_filing"]),
        *[
            process_bank_statement_page.s(app_id, pid, pnum, manifest["bank_statement"])
            for pnum, pid in enumerate(page_ids, start=1)
        ],
    ]

    # Stage 3: Fan-in aggregation callback
    t_chord_start = time.perf_counter()
    workflow = chord(header)(aggregate_underwriting_decision.s(app_id, requested_facility))
    decision = workflow.get()
    t_chord_end = time.perf_counter()

    total_duration_ms = (time.perf_counter() - t0) * 1000
    chord_duration_ms = (t_chord_end - t_chord_start) * 1000

    return {
        "mode": "parallel",
        "application_id": app_id,
        "page_count": len(page_ids),
        "total_tasks": len(page_ids) + 2,
        "total_duration_ms": round(total_duration_ms, 2),
        "validation_duration_ms": round(val_duration_ms, 2),
        "chord_duration_ms": round(chord_duration_ms, 2),
        "stage_timings": decision.get("stage_timings", {}),
        "decision": decision.get("decision"),
    }


def execute_benchmarks(iterations: int = 3) -> list[dict[str, Any]]:
    """Run sequential and parallel benchmarks across all registered dossier fixtures."""
    # Ensure Celery runs in eager mode for reproducible in-memory benchmarking
    orig_eager = celery_app.conf.task_always_eager
    orig_prop = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    try:
        manifests = get_dossier_manifests()
        benchmarks: list[dict[str, Any]] = []

        for name, manifest in manifests.items():
            seq_times: list[float] = []
            par_times: list[float] = []
            page_count = 0
            decision = ""

            for _ in range(iterations):
                seq_res = run_sequential(manifest)
                par_res = run_parallel(manifest)

                seq_times.append(seq_res["total_duration_ms"])
                par_times.append(par_res["total_duration_ms"])
                page_count = seq_res["page_count"]
                decision = par_res["decision"]

            avg_seq_ms = round(sum(seq_times) / len(seq_times), 2)
            avg_par_ms = round(sum(par_times) / len(par_times), 2)
            speedup = round(avg_seq_ms / avg_par_ms, 2) if avg_par_ms > 0 else 1.0

            benchmarks.append({
                "dossier": name,
                "pages": page_count,
                "parallel_tasks": page_count + 2,
                "iterations": iterations,
                "sequential_ms": avg_seq_ms,
                "parallel_ms": avg_par_ms,
                "speedup_ratio": speedup,
                "decision": decision,
            })

        return benchmarks
    finally:
        celery_app.conf.task_always_eager = orig_eager
        celery_app.conf.task_eager_propagates = orig_prop


def format_markdown_table(results: list[dict[str, Any]]) -> str:
    """Format benchmark results into a clean GitHub Flavored Markdown table."""
    lines = [
        "### Concurrency Benchmark: Sequential vs. Parallel Chord Execution",
        "",
        "| Dossier Specimen | Statement Pages | Parallel Tasks | Sequential Latency ($T_{\\text{seq}}$) | Parallel Latency ($T_{\\text{par}}$) | Speedup ($T_{\\text{seq}} / T_{\\text{par}}$) | Outcome |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in results:
        lines.append(
            f"| `{r['dossier']}` | {r['pages']} | {r['parallel_tasks']} | "
            f"{r['sequential_ms']:.2f} ms | {r['parallel_ms']:.2f} ms | "
            f"**{r['speedup_ratio']:.2f}x** | `{r['decision']}` |"
        )
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append(
        "> Sequential latency scales linearly with $O(P)$ as each page is parsed serially. "
        "The parallel `chord` distributes page tasks across worker slots, collapsing multi-page duration to $O(\\lceil P/C \\rceil)$."
    )
    return "\n".join(lines)


def main() -> None:
    """CLI entrypoint for running the concurrency benchmark."""
    parser = argparse.ArgumentParser(description="Run Celery workflow concurrency benchmarks.")
    parser.add_argument("--iterations", type=int, default=3, help="Number of iterations to average.")
    parser.add_argument("--output-json", type=str, default=None, help="Optional path to save JSON results.")
    args = parser.parse_args()

    print(f"Starting underwriting workflow benchmark ({args.iterations} iterations)...")
    results = execute_benchmarks(iterations=args.iterations)

    md_table = format_markdown_table(results)
    print("\n" + md_table + "\n")

    if args.output_json:
        out_path = Path(args.output_json)
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"JSON results saved to {out_path}")


if __name__ == "__main__":
    main()

