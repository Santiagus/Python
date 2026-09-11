"""Unit tests for domain document processors (KYC, Bank Statement, Tax Return).

These tests verify isolated parsing, mathematical calculations, OCR thresholding,
and Result Envelope structures without requiring an external broker or Celery worker.
"""

from pathlib import Path
import pytest

from services.worker.processors.kyc_processor import KYCProcessor
from services.worker.processors.statement_processor import StatementProcessor
from services.worker.processors.tax_processor import TaxProcessor


class TestKYCProcessor:
    """Test identity document parsing and validation."""

    def test_extract_kyc_specimen(self, clean_dossier_manifest: dict[str, str]) -> None:
        """Verify extraction of identity fields from the official specimen photo ID."""
        processor = KYCProcessor()
        file_path = clean_dossier_manifest["kyc_id"]
        result = processor.process(file_path, expected_applicant="JANE DOE")

        assert result["status"] == "success"
        assert result["document_type"] == "kyc_id"
        data = result["data"]
        assert data["full_name"] == "JANE DOE"
        assert "DL-9843210-CA" in data["document_number"]
        assert data["is_expired"] is False
        assert result["errors"] == []

    def test_kyc_name_mismatch(self, clean_dossier_manifest: dict[str, str]) -> None:
        """Verify that a mismatch between applicant name and ID is detected and flagged."""
        processor = KYCProcessor()
        file_path = clean_dossier_manifest["kyc_id"]
        result = processor.process(file_path, expected_applicant="MARK DAVIS")

        assert result["status"] == "failed"
        assert len(result["errors"]) > 0
        assert any("mismatch" in err.lower() for err in result["errors"])


class TestStatementProcessor:
    """Test bank statement PDF ledger parsing and OCR confidence scoring."""

    def test_clean_4pages_statement(self, clean_dossier_manifest: dict[str, str]) -> None:
        """Verify clean 4-page statement parsing, transaction aggregation, and cashflow math."""
        processor = StatementProcessor()
        file_path = clean_dossier_manifest["bank_statement"]
        partition = processor.partition_pages(file_path)

        assert partition["total_pages"] == 4
        assert len(partition["pages"]) == 4

        # Process each page independently
        page_results = [processor.process_page_content(p["page_number"], p["text"]) for p in partition["pages"]]
        for pr in page_results:
            assert pr["status"] == "success"
            assert pr["confidence"] >= 0.70

        # Verify full document ledger summary
        summary = processor.aggregate_pages(page_results)
        assert summary["starting_balance"] == 50000.00
        assert summary["closing_balance"] == 82549.50
        assert summary["net_cashflow"] == 32549.50
        assert summary["total_deposits"] == 64200.00
        assert summary["total_withdrawals"] == 31650.50

    def test_degraded_statement_page2(self, degraded_dossier_manifest: dict[str, str]) -> None:
        """Verify that degraded OCR noise on Page 2 triggers a degraded Result Envelope."""
        processor = StatementProcessor()
        file_path = degraded_dossier_manifest["bank_statement"]
        partition = processor.partition_pages(file_path)

        assert partition["total_pages"] == 3

        # Page 1 should be clean
        p1 = processor.process_page_content(1, partition["pages"][0]["text"])
        assert p1["status"] == "success"
        assert p1["confidence"] >= 0.70

        # Page 2 should be flagged degraded
        p2 = processor.process_page_content(2, partition["pages"][1]["text"])
        assert p2["status"] == "degraded"
        assert p2["confidence"] < 0.70
        assert len(p2["errors"]) > 0


class TestTaxProcessor:
    """Test corporate income tax return (IRS Form 1120) parsing."""

    def test_clean_tax_filing(self, clean_dossier_manifest: dict[str, str]) -> None:
        """Verify Form 1120 P&L and balance sheet metric extraction."""
        processor = TaxProcessor()
        file_path = clean_dossier_manifest["tax_filing"]
        result = processor.process(file_path)

        assert result["status"] == "success"
        data = result["data"]
        assert data["gross_receipts"] == 1450000.00
        assert data["cogs"] == 480000.00
        assert data["total_deductions"] == 739000.00
        assert data["taxable_income"] == 206000.00
        assert data["ebitda"] == 244500.00
        assert data["dscr_baseline"] == 3.25
        assert data["officer_name"] == "JANE DOE"

