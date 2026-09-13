"""Domain document processors package for underwriting workflow.

Exports:
- KYCProcessor: Photographic ID specimen parsing and applicant fraud verification.
- StatementProcessor: PDF transaction ledger partitioning, OCR quality scoring, and cashflow aggregation.
- TaxProcessor: Corporate tax return (IRS Form 1120) parsing and DSCR solvency calculation.
- CorruptedDocumentError: Custom exception for malformed document binaries.
"""

from __future__ import annotations

from .kyc_processor import KYCProcessor
from .statement_processor import CorruptedDocumentError, StatementProcessor
from .tax_processor import TaxProcessor

__all__ = [
    "KYCProcessor",
    "StatementProcessor",
    "TaxProcessor",
    "CorruptedDocumentError",
]

