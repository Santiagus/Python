"""Unit tests for domain document processors (KYC, Bank Statement, Tax Return).

These tests verify isolated parsing, mathematical calculations, OCR thresholding,
and Result Envelope structures without requiring an external broker or Celery worker.
"""

from decimal import Decimal
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

    def test_kyc_file_not_found(self) -> None:
        """Verify handling when KYC file does not exist."""
        processor = KYCProcessor()
        result = processor.process("/nonexistent/path/id.jpg")
        assert result["status"] == "failed"
        assert any("not found" in err.lower() for err in result["errors"])

    def test_kyc_read_os_error(self, clean_dossier_manifest: dict[str, str], monkeypatch) -> None:
        """Verify handling when file read raises OSError."""
        processor = KYCProcessor()
        file_path = clean_dossier_manifest["kyc_id"]

        def mock_read_bytes(self):
            raise OSError("I/O failure during disk read")

        monkeypatch.setattr(Path, "read_bytes", mock_read_bytes)
        result = processor.process(file_path)
        assert result["status"] == "failed"
        assert any("cannot read" in err.lower() for err in result["errors"])

    def test_kyc_invalid_image_format(self, tmp_path: Path) -> None:
        """Verify handling when file lacks JPEG/PNG magic bytes."""
        bad_file = tmp_path / "corrupted.jpg"
        bad_file.write_bytes(b"INVALID_HEADER_DATA_123456789")
        processor = KYCProcessor()
        result = processor.process(str(bad_file))
        assert result["status"] == "failed"
        assert any("unsupported" in err.lower() for err in result["errors"])

    def test_kyc_expired_document_flagged(self, tmp_path: Path) -> None:
        """Verify expired KYC document generates failure and audit error."""
        expired_file = tmp_path / "expired_dl.jpg"
        expired_file.write_bytes(b"\xff\xd8\xff\xe0" + b"EXPIRED_DRIVER_LICENSE_DATA")
        processor = KYCProcessor()
        result = processor.process(str(expired_file))
        assert result["status"] == "failed"
        assert any("expired" in err.lower() for err in result["errors"])


class TestStatementProcessor:
    """Test bank statement PDF ledger parsing and OCR confidence scoring."""

    def test_currency_parsing_edge_cases(self) -> None:
        """Verify _parse_currency handles empty strings, None, and invalid formats."""
        """Verify _parse_currency handles empty strings, None, and invalid formats in minor units and Decimal."""
        assert StatementProcessor._parse_currency(None) is None
        assert StatementProcessor._parse_currency("") is None
        assert StatementProcessor._parse_currency("   ") is None
        assert StatementProcessor._parse_currency("NOT_A_NUM") is None
        assert StatementProcessor._parse_currency("$1,250.75") == 1250.75
        assert StatementProcessor._parse_currency("$1,250.75") == Decimal("1250.75")
        assert StatementProcessor._parse_currency_cents("$1,250.75") == 125075
        assert StatementProcessor._parse_currency_cents(None) is None

    def test_partition_missing_file_raises_corrupted_error(self) -> None:
        """Verify partition_pages raises CorruptedDocumentError if file does not exist."""
        from services.worker.processors import CorruptedDocumentError
        processor = StatementProcessor()
        with pytest.raises(CorruptedDocumentError, match="not found"):
            processor.partition_pages("/nonexistent/file.pdf")

    def test_partition_invalid_header_raises_corrupted_error(self, tmp_path: Path) -> None:
        """Verify partition_pages raises CorruptedDocumentError if PDF header is missing."""
        from services.worker.processors import CorruptedDocumentError
        bad_pdf = tmp_path / "bad.pdf"
        bad_pdf.write_bytes(b"NOT_A_PDF_STREAM")
        processor = StatementProcessor()
        with pytest.raises(CorruptedDocumentError, match="Invalid PDF header"):
            processor.partition_pages(bad_pdf)

    def test_partition_truncated_structure_raises_corrupted_error(self, tmp_path: Path) -> None:
        """Verify partition_pages raises CorruptedDocumentError if PDF is truncated (no EOF)."""
        from services.worker.processors import CorruptedDocumentError
        trunc_pdf = tmp_path / "truncated.pdf"
        trunc_pdf.write_bytes(b"%PDF-1.4\nSome text without end of file marker")
        processor = StatementProcessor()
        with pytest.raises(CorruptedDocumentError, match="Corrupted or truncated PDF structure"):
            processor.partition_pages(trunc_pdf)

    def test_partition_no_streams_raises_corrupted_error(self, tmp_path: Path) -> None:
        """Verify partition_pages raises CorruptedDocumentError if no content streams are found."""
        from services.worker.processors import CorruptedDocumentError
        no_stream_pdf = tmp_path / "no_stream.pdf"
        no_stream_pdf.write_bytes(b"%PDF-1.4\nSome metadata\n%%EOF")
        processor = StatementProcessor()
        with pytest.raises(CorruptedDocumentError, match="No content streams found"):
            processor.partition_pages(no_stream_pdf)

    def test_clean_4pages_statement(self, clean_dossier_manifest: dict[str, str]) -> None:
        """Verify clean 4-page statement parsing, transaction aggregation, and cashflow math."""
        """Verify clean 4-page statement parsing, transaction aggregation, and minor-unit cashflow math."""
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
        # Verify full document ledger summary in both minor units (cents) and exact Decimal
        summary = processor.aggregate_pages(page_results)
        assert summary["starting_balance"] == 50000.00
        assert summary["closing_balance"] == 82549.50
        assert summary["net_cashflow"] == 32549.50
        assert summary["total_deposits"] == 64200.00
        assert summary["total_withdrawals"] == 31650.50
        assert summary["starting_balance_cents"] == 5000000
        assert summary["closing_balance_cents"] == 8254950
        assert summary["net_cashflow_cents"] == 3254950
        assert summary["total_deposits_cents"] == 6420000
        assert summary["total_withdrawals_cents"] == 3165050

        assert summary["starting_balance"] == Decimal("50000.00")
        assert summary["closing_balance"] == Decimal("82549.50")
        assert summary["net_cashflow"] == Decimal("32549.50")
        assert summary["total_deposits"] == Decimal("64200.00")
        assert summary["total_withdrawals"] == Decimal("31650.50")

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

    def test_aggregate_pages_legacy_fallback(self) -> None:
        """Verify aggregate_pages correctly falls back to Decimal keys when _cents are omitted."""
        processor = StatementProcessor()
        page_results = [
            {
                "page_number": 1,
                "starting_balance": Decimal("1000.00"),
            },
            {
                "page_number": 2,
                "total_deposits": Decimal("500.00"),
                "total_withdrawals": Decimal("200.00"),
            },
        ]
        agg = processor.aggregate_pages(page_results)
        assert agg["starting_balance_cents"] == 100000
        assert agg["total_deposits_cents"] == 50000
        assert agg["total_withdrawals_cents"] == 20000
        assert agg["net_cashflow_cents"] == 30000
        assert agg["closing_balance_cents"] == 130000


class TestTaxProcessor:
    """Test corporate income tax return (IRS Form 1120) parsing."""

    def test_currency_parsing_edge_cases(self) -> None:
        """Verify _parse_currency handles empty strings, None, and invalid formats."""
        assert TaxProcessor._parse_currency(None) == 0.0
        assert TaxProcessor._parse_currency("") == 0.0
        assert TaxProcessor._parse_currency("   ") == 0.0
        assert TaxProcessor._parse_currency("NOT_A_NUM") == 0.0
        assert TaxProcessor._parse_currency("$1,500,000.00") == 1500000.00
        assert TaxProcessor._parse_currency(None) == Decimal("0.00")
        assert TaxProcessor._parse_currency("") == Decimal("0.00")
        assert TaxProcessor._parse_currency("   ") == Decimal("0.00")
        assert TaxProcessor._parse_currency("NOT_A_NUM") == Decimal("0.00")
        assert TaxProcessor._parse_currency("$1,500,000.00") == Decimal("1500000.00")
        assert TaxProcessor._parse_currency_cents("$1,500,000.00") == 150000000
        assert TaxProcessor._parse_currency_cents(None) == 0

    def test_tax_file_not_found(self) -> None:
        """Verify processing returns failed status when file is not found."""
        processor = TaxProcessor()
        result = processor.process("/nonexistent/tax.pdf")
        assert result["status"] == "failed"
        assert any("not found" in err.lower() for err in result["errors"])

    def test_clean_tax_filing(self, clean_dossier_manifest: dict[str, str]) -> None:
        """Verify Form 1120 P&L and balance sheet metric extraction."""
        """Verify Form 1120 P&L and balance sheet metric extraction in minor units and Decimal."""
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
        assert data["gross_receipts_cents"] == 145000000
        assert data["cogs_cents"] == 48000000
        assert data["total_deductions_cents"] == 73900000
        assert data["taxable_income_cents"] == 20600000
        assert data["ebitda_cents"] == 24450000

        assert data["gross_receipts"] == Decimal("1450000.00")
        assert data["cogs"] == Decimal("480000.00")
        assert data["total_deductions"] == Decimal("739000.00")
        assert data["taxable_income"] == Decimal("206000.00")
        assert data["ebitda"] == Decimal("244500.00")
        assert data["dscr_baseline"] == Decimal("3.25")
        assert data["officer_name"] == "JANE DOE"

