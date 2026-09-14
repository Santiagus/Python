"""Unit tests for the scripts/benchmark.py concurrency benchmark harness."""

from pathlib import Path
import pytest

from scripts.benchmark import (
    execute_benchmarks,
    format_markdown_table,
    get_dossier_manifests,
    run_parallel,
    run_sequential,
)


def test_get_dossier_manifests_paths_exist() -> None:
    """Verify get_dossier_manifests returns existing fixture paths for 4-page and 16-page dossiers."""
    manifests = get_dossier_manifests()
    assert "4_pages_clean" in manifests
    assert "16_pages_benchmark" in manifests

    for name, manifest in manifests.items():
        assert Path(manifest["bank_statement"]).exists(), f"Missing bank_statement for {name}"
        assert Path(manifest["kyc_id"]).exists(), f"Missing kyc_id for {name}"
        assert Path(manifest["tax_filing"]).exists(), f"Missing tax_filing for {name}"


def test_run_sequential_happy_path() -> None:
    """Verify run_sequential executes step-by-step and returns valid timing structure."""
    manifests = get_dossier_manifests()
    res = run_sequential(manifests["4_pages_clean"])

    assert res["mode"] == "sequential"
    assert res["page_count"] == 4
    assert res["total_tasks"] == 6
    assert res["total_duration_ms"] > 0
    assert res["validation_duration_ms"] > 0
    assert res["pages_duration_ms"] > 0
    assert res["decision"] == "approved"


def test_run_parallel_happy_path() -> None:
    """Verify run_parallel executes Celery chord and returns valid timing structure."""
    manifests = get_dossier_manifests()
    res = run_parallel(manifests["4_pages_clean"])

    assert res["mode"] == "parallel"
    assert res["page_count"] == 4
    assert res["total_tasks"] == 6
    assert res["total_duration_ms"] > 0
    assert res["validation_duration_ms"] > 0
    assert res["chord_duration_ms"] > 0
    assert res["decision"] == "approved"


def test_execute_benchmarks_and_format_markdown() -> None:
    """Verify execute_benchmarks runs across fixtures and formats clean markdown table."""
    results = execute_benchmarks(iterations=1)

    assert len(results) == 2
    for r in results:
        assert r["pages"] in (4, 16)
        assert r["sequential_ms"] > 0
        assert r["parallel_ms"] > 0
        assert r["speedup_ratio"] > 0
        assert r["decision"] == "approved"

    md = format_markdown_table(results)
    assert "### Concurrency Benchmark" in md
    assert "4_pages_clean" in md
    assert "16_pages_benchmark" in md
    assert "Speedup" in md

