"""Corporate tax filing (IRS Form 1120) processor.

Extracts financial statement metrics (Gross Receipts, COGS, Deductions,
Taxable Income, EBITDA, and Baseline DSCR) from Adobe PDF streams.
"""

from __future__ import annotations

from decimal import Decimal
import logging
from pathlib import Path
import re
from pathlib import Path
from typing import Any

from app.currency import cents_to_decimal, parse_currency_to_cents

logger = logging.getLogger(__name__)


class TaxProcessor:
    """Parses corporate tax filings (IRS Form 1120) and computes financial ratios."""

    @staticmethod
    def _parse_currency(val_str: str | None) -> Decimal:
        cents = parse_currency_to_cents(val_str)
        return cents_to_decimal(cents) if cents is not None else Decimal("0.00")

    @staticmethod
    def _parse_currency_cents(val_str: str | None) -> int:
        cents = parse_currency_to_cents(val_str)
        return cents if cents is not None else 0

    def process(self, file_path: str | Path) -> dict[str, Any]:
        """Parse an IRS Form 1120 PDF tax filing and extract key solvency metrics.

        Args:
            file_path: Path to the tax return PDF.

        Returns:
            Result Envelope dictionary with extracted P&L metrics and calculated ratios.
        """
        path = Path(file_path)
        if not path.exists():
            return {
                "status": "failed",
                "document_type": "tax_filing",
                "data": {},
                "errors": [f"Tax filing file not found: {path}"],
            }

        data = path.read_bytes()
        streams = re.findall(b"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL)
        all_lines: list[str] = []
        for s in streams:
            text_content = s.decode("latin1", errors="replace")
            raw_lines = re.findall(r"\((.*?)\) \x27", text_content)
            all_lines.extend(
                [l.replace("\\\\", "\\").replace("\\(", "(").replace("\\)", ")") for l in raw_lines]
            )

        full_text = "\n".join(all_lines)

        gross_m = re.search(r"Gross receipts or sales[\.\s]+\$\s*([\d,]+\.\d{2})", full_text)
        cogs_m = re.search(r"Cost of goods sold \(COGS\)[\.\s]+\$\s*([\d,]+\.\d{2})", full_text)
        deductions_m = re.search(
            r"Total deductions\. Add lines 12 through 26[\.\s]+\$\s*([\d,]+\.\d{2})", full_text
        )
        taxable_m = re.search(
            r"Taxable income before NOL[^\$]+\$\s*([\d,]+\.\d{2})", full_text
        )
        ebitda_m = re.search(r"Calculated Annual EBITDA[\.\s]+\$\s*([\d,]+\.\d{2})", full_text)
        dscr_m = re.search(
            r"Debt Service Coverage Ratio \(DSCR Baseline\)[\.\s]+([\d\.]+)x?", full_text
        )
        officer_m = re.search(r"Officer(?:\s+Name)?:\s*([A-Za-z\s]+?)(?:,|\n|$)", full_text)

        gross_receipts_cents = parse_currency_to_cents(gross_m.group(1)) if gross_m else 0
        cogs_cents = parse_currency_to_cents(cogs_m.group(1)) if cogs_m else 0
        total_deductions_cents = parse_currency_to_cents(deductions_m.group(1)) if deductions_m else 0
        taxable_income_cents = parse_currency_to_cents(taxable_m.group(1)) if taxable_m else 0
        ebitda_cents = parse_currency_to_cents(ebitda_m.group(1)) if ebitda_m else 0
        dscr_baseline = Decimal(dscr_m.group(1)) if dscr_m else Decimal("0.0")
        officer_name = officer_m.group(1).strip() if officer_m else ""

        parsed_data = {
            "gross_receipts_cents": gross_receipts_cents or 0,
            "cogs_cents": cogs_cents or 0,
            "total_deductions_cents": total_deductions_cents or 0,
            "taxable_income_cents": taxable_income_cents or 0,
            "ebitda_cents": ebitda_cents or 0,
            "gross_receipts": cents_to_decimal(gross_receipts_cents) or Decimal("0.00"),
            "cogs": cents_to_decimal(cogs_cents) or Decimal("0.00"),
            "total_deductions": cents_to_decimal(total_deductions_cents) or Decimal("0.00"),
            "taxable_income": cents_to_decimal(taxable_income_cents) or Decimal("0.00"),
            "ebitda": cents_to_decimal(ebitda_cents) or Decimal("0.00"),
            "dscr_baseline": dscr_baseline,
            "officer_name": officer_name,
        }

        logger.debug(
            "tax_filing_processed",
            extra={
                "file_path": str(path),
                "gross_receipts": parsed_data["gross_receipts"],
                "ebitda": parsed_data["ebitda"],
                "dscr_baseline": parsed_data["dscr_baseline"],
            },
        )

        return {
            "status": "success",
            "document_type": "tax_filing",
            "data": parsed_data,
            "errors": [],
        }

