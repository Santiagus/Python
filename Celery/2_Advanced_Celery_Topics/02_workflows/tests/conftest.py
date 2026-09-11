"""Pytest fixtures and configuration for Module 02 test suite."""

import os
import sys
from pathlib import Path
from typing import Generator
import pytest

# Ensure 02_workflows root is in sys.path
MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Return the absolute path to the tests/fixtures directory."""
    p = MODULE_ROOT / "tests" / "fixtures"
    assert p.exists(), f"Fixtures directory not found at {p}"
    return p


@pytest.fixture
def clean_dossier_manifest(fixtures_dir: Path) -> dict[str, str]:
    """Return paths for the happy path 4-page clean dossier."""
    clean_dir = fixtures_dir / "clean_4pages"
    return {
        "bank_statement": str(clean_dir / "bank_statement_4pages.pdf"),
        "kyc_id": str(clean_dir / "kyc_executive_id.jpg"),
        "tax_filing": str(clean_dir / "tax_filing_irs1120.pdf"),
    }


@pytest.fixture
def degraded_dossier_manifest(fixtures_dir: Path) -> dict[str, str]:
    """Return paths for the degraded statement dossier (Page 2 OCR noise)."""
    return {
        "bank_statement": str(fixtures_dir / "degraded_page2" / "bank_statement_degraded.pdf"),
        "kyc_id": str(fixtures_dir / "clean_4pages" / "kyc_executive_id.jpg"),
        "tax_filing": str(fixtures_dir / "clean_4pages" / "tax_filing_irs1120.pdf"),
    }


@pytest.fixture
def corrupted_dossier_manifest(fixtures_dir: Path) -> dict[str, str]:
    """Return paths for the corrupted statement dossier (malformed binary)."""
    return {
        "bank_statement": str(fixtures_dir / "corrupted" / "corrupted_statement.pdf"),
        "kyc_id": str(fixtures_dir / "clean_4pages" / "kyc_executive_id.jpg"),
        "tax_filing": str(fixtures_dir / "clean_4pages" / "tax_filing_irs1120.pdf"),
    }


@pytest.fixture
def benchmark_dossier_manifest(fixtures_dir: Path) -> dict[str, str]:
    """Return paths for the 16-page benchmark statement dossier."""
    return {
        "bank_statement": str(fixtures_dir / "benchmark_16pages" / "bank_statement_16pages.pdf"),
        "kyc_id": str(fixtures_dir / "clean_4pages" / "kyc_executive_id.jpg"),
        "tax_filing": str(fixtures_dir / "clean_4pages" / "tax_filing_irs1120.pdf"),
    }

