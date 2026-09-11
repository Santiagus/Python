#!/usr/bin/env python3
"""Synthetic financial dataset generator for Celery workflows (Module 02).

Produces deterministic, reproducible test dossiers:
1. Executive KYC Identity Document (High-resolution specimen driver's license image).
2. Multi-Page Corporate Bank Statements (Valid Adobe PDF 1.4 with realistic transaction tables).
3. Corporate Tax Filing (IRS Form 1120 / P&L statement in PDF format).
4. Degraded statement with low OCR confidence noise to test partial failure envelopes.
5. Corrupted binary file to test link_error compensating callbacks.

Implemented using only Python standard library (no external heavy PDF/imaging dependencies required).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


# ==============================================================================
# Pure-Python Minimal Adobe PDF 1.4 Generator
# ==============================================================================

class MinimalPDFBuilder:
    """Generates standard-compliant Adobe PDF 1.4 documents with text streams."""

    def __init__(self) -> None:
        self.pages: list[list[str]] = []

    def add_page(self, lines: list[str]) -> None:
        """Add a page consisting of plain text lines."""
        self.pages.append(lines)

    def build_bytes(self) -> bytes:
        """Compile pages into a valid PDF 1.4 byte sequence with standard cross-reference table."""
        if not self.pages:
            raise ValueError("PDF must contain at least one page.")

        font_id = 3
        page_ids: list[int] = []
        content_ids: list[int] = []
        curr_id = 4

        for _ in self.pages:
            page_ids.append(curr_id)
            content_ids.append(curr_id + 1)
            curr_id += 2

        obj_dict: dict[int, bytes] = {}
        # Object 1: Catalog
        obj_dict[1] = b"<< /Type /Catalog /Pages 2 0 R >>"

        # Object 2: Pages tree
        kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
        obj_dict[2] = f"<< /Type /Pages /Kids [{kids_str}] /Count {len(self.pages)} >>".encode("latin1")

        # Object 3: Helvetica Font
        obj_dict[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

        # Build each page and its content stream
        for i, lines in enumerate(self.pages):
            pid = page_ids[i]
            cid = content_ids[i]

            stream_cmds = [
                "BT",
                "/F1 10 Tf",
                "40 750 Td",
                "14 TL",
            ]
            for line in lines:
                escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                stream_cmds.append(f"({escaped}) '")
            stream_cmds.append("ET")

            stream_bytes = "\n".join(stream_cmds).encode("latin1", errors="replace")
            obj_dict[cid] = (
                f"<< /Length {len(stream_bytes)} >>\nstream\n".encode("latin1")
                + stream_bytes
                + b"\nendstream"
            )
            obj_dict[pid] = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {cid} 0 R >>"
            ).encode("latin1")

        # Assemble PDF byte stream and record object offsets
        output: list[bytes] = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
        offsets: dict[int, int] = {}

        all_ids = sorted(obj_dict.keys())
        for oid in all_ids:
            offsets[oid] = sum(len(chunk) for chunk in output)
            output.append(f"{oid} 0 obj\n".encode("latin1") + obj_dict[oid] + b"\nendobj\n")

        # Cross-reference table
        xref_offset = sum(len(chunk) for chunk in output)
        total_objects = max(all_ids) + 1

        output.append(f"xref\n0 {total_objects}\n".encode("latin1"))
        output.append(b"0000000000 65535 f \n")
        for oid in range(1, total_objects):
            off = offsets.get(oid, 0)
            output.append(f"{off:010d} 00000 n \n".encode("latin1"))

        # Trailer
        output.append(
            f"trailer\n<< /Size {total_objects} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("latin1")
        )
        return b"".join(output)



# ==============================================================================
# Bank Statement Content Generator
# ==============================================================================

def generate_bank_statement_pages(
    page_count: int = 4,
    degrade_page: int | None = None,
) -> list[list[str]]:
    """Builds multi-page transaction ledger pages for a commercial checking account."""
    pages: list[list[str]] = []
    running_balance = 50000.00  # Initial balance: $50,000.00

    transactions_library = [
        ("2026-08-02", "STRIPE PAYOUT - MERCHANT DEPOSIT", 14500.00, 0.0),
        ("2026-08-04", "AWS CLOUD HOSTING - RECURRING DEBIT", 0.0, 1850.50),
        ("2026-08-07", "GUSTO PAYROLL SERVICES - SALARIES", 0.0, 12400.00),
        ("2026-08-10", "CUSTOMER WIRE TRANSFER INFLOW", 22000.00, 0.0),
        ("2026-08-12", "COMMERCIAL REALTY CORP - OFFICE LEASE", 0.0, 4200.00),
        ("2026-08-15", "GOOGLE WORKSPACE & CLOUD SERVICES", 0.0, 680.00),
        ("2026-08-18", "STRIPE PAYOUT - MERCHANT DEPOSIT", 18200.00, 0.0),
        ("2026-08-20", "SLACK TECHNOLOGIES - ANNUAL SUB", 0.0, 1500.00),
        ("2026-08-22", "EQUIPMENT FINANCING MONTHLY DEBIT", 0.0, 3100.00),
        ("2026-08-25", "CUSTOMER ACH PAYMENT REF#49102", 9500.00, 0.0),
        ("2026-08-28", "STATE TAX BOARD - ESTIMATED TAXES", 0.0, 5000.00),
        ("2026-08-30", "MERCHANT ACCOUNT PROCESSING FEES", 0.0, 420.00),
    ]

    for p in range(1, page_count + 1):
        lines: list[str] = [
            "================================================================================",
            "SILICON VALLEY COMMERCIAL BANK - MONTHLY ACCOUNT STATEMENT",
            "================================================================================",
            f"Account: 1048-5928-8821       Routing: 121000358       Period: 2026-08-01 to 2026-08-31",
            f"Entity: APEX FINTECH DYNAMICS INC.                      Page {p} of {page_count}",
            "--------------------------------------------------------------------------------",
        ]

        if p == 1:
            lines.extend([
                f"Starting Balance:                  ${running_balance:,.2f}",
                "Statement Currency:                USD",
                "Account Type:                      Commercial Operating Account",
                "--------------------------------------------------------------------------------",
            ])

        # If this page is designated as degraded (Use Case 2), inject OCR failure markers
        if degrade_page is not None and p == degrade_page:
            lines.extend([
                "TRANSACTION ACTIVITY LEDGER",
                "DATE       DESCRIPTION                                CREDIT       DEBIT        BALANCE",
                "--------------------------------------------------------------------------------",
                "!@#$%^&*() CORRUPTED SCAN LINE TORN SCANNER FEED JAMMED [OCR_ERROR: LOW_CONTRAST]",
                "~~##??!!   UNKNOWN ARTIFACT DETECTED - CONFIDENCE_SCORE: 32% (THRESHOLD: 70%)",
                "2026-08-?? UNREADABLE SMUDGE [UNRECOGNIZED_GLYPH]       ???.??       ???.??       ???.??",
                "--------------------------------------------------------------------------------",
                "WARNING: OPTICAL CHARACTER RECOGNITION CONFIDENCE FAILED ON THIS PAGE SECTION.",
            ])
        else:
            lines.extend([
                "TRANSACTION ACTIVITY LEDGER",
                "DATE       DESCRIPTION                                CREDIT       DEBIT        BALANCE",
                "--------------------------------------------------------------------------------",
            ])
            # Inject 4-6 deterministic transactions per page
            for i in range(5):
                tx_idx = ((p - 1) * 5 + i) % len(transactions_library)
                date, desc, credit, debit = transactions_library[tx_idx]
                if credit > 0:
                    running_balance += credit
                    lines.append(f"{date} {desc:<40} ${credit:>10,.2f}             ${running_balance:>10,.2f}")
                else:
                    running_balance -= debit
                    lines.append(f"{date} {desc:<40}             ${debit:>10,.2f} ${running_balance:>10,.2f}")

        if p == page_count:
            lines.extend([
                "--------------------------------------------------------------------------------",
                f"Closing Statement Balance:         ${running_balance:,.2f}",
                "Total Monthly Deposits:            $64,200.00",
                "Total Monthly Withdrawals:         $31,650.50",
                "Net Cash Flow Change:              +$32,549.50",
                "================================================================================",
            ])

        pages.append(lines)

    return pages


# ==============================================================================
# Corporate Tax Filing Generator (IRS Form 1120 / P&L)
# ==============================================================================

def generate_tax_filing_pages() -> list[list[str]]:
    """Builds a 2-page Corporate Income Tax Return (IRS Form 1120)."""
    p1 = [
        "================================================================================",
        "FORM 1120: U.S. CORPORATION INCOME TAX RETURN (OMB No. 1545-0123)",
        "For calendar year 2025 or tax year beginning 01-01-2025 and ending 12-31-2025",
        "================================================================================",
        "Entity: APEX FINTECH DYNAMICS INC.             Employer Identification No (EIN): 12-3456789",
        "Address: 450 MISSION ST, SAN FRANCISCO, CA 94105   State of Incorporation: DELAWARE",
        "--------------------------------------------------------------------------------",
        "INCOME ANALYSIS",
        "1a  Gross receipts or sales ..................................... $1,450,000.00",
        "1b  Returns and allowances ...................................... $   25,000.00",
        "1c  Balance. Subtract line 1b from line 1a ..................... $1,425,000.00",
        "2   Cost of goods sold (COGS) ................................... $  480,000.00",
        "3   Gross profit. Subtract line 2 from line 1c .................. $  945,000.00",
        "--------------------------------------------------------------------------------",
        "DEDUCTIONS & OPERATING EXPENSES",
        "12  Compensation of officers .................................... $  220,000.00",
        "13  Salaries and wages (less employment credits) ................ $  340,000.00",
        "14  Repairs and maintenance ..................................... $   18,000.00",
        "16  Rents paid .................................................. $   48,000.00",
        "17  Taxes and licenses .......................................... $   32,000.00",
        "18  Interest expense ............................................ $   14,500.00",
        "20  Depreciation and amortization ............................... $   24,000.00",
        "26  Other deductions ............................................ $   42,500.00",
        "27  Total deductions. Add lines 12 through 26 .................. $  739,000.00",
        "--------------------------------------------------------------------------------",
        "TAXABLE INCOME & SOLVENCY METRICS",
        "28  Taxable income before NOL. Subtract line 27 from line 3 ..... $  206,000.00",
        "    Calculated Annual EBITDA .................................... $  244,500.00",
        "    Debt Service Coverage Ratio (DSCR Baseline) ................. 3.25x",
        "================================================================================",
    ]

    p2 = [
        "================================================================================",
        "FORM 1120: SCHEDULE L - BALANCE SHEETS PER BOOKS",
        "================================================================================",
        "ASSETS                                              BEGINNING OF YEAR   END OF YEAR",
        "1   Cash and cash equivalents ..................... $  120,000.00      $  245,000.00",
        "2a  Trade notes and accounts receivable ........... $   85,000.00      $  110,000.00",
        "3   Inventories ................................... $   45,000.00      $   38,000.00",
        "10a Buildings and other depreciable assets ........ $  180,000.00      $  210,000.00",
        "15  Total assets .................................. $  430,000.00      $  603,000.00",
        "--------------------------------------------------------------------------------",
        "LIABILITIES AND SHAREHOLDERS' EQUITY",
        "16  Accounts payable .............................. $   52,000.00      $   64,000.00",
        "17  Mortgages, notes, bonds payable in < 1 year ... $   28,000.00      $   30,000.00",
        "20  Mortgages, notes, bonds payable in >= 1 year .. $   85,000.00      $   75,000.00",
        "22  Capital stock ................................. $   50,000.00      $   50,000.00",
        "25  Retained earnings ............................. $  215,000.00      $  384,000.00",
        "26  Total liabilities and shareholders' equity .... $  430,000.00      $  603,000.00",
        "================================================================================",
    ]
    return [p1, p2]


# ==============================================================================
# Master Generation Routines
# ==============================================================================

def generate_all_fixtures(target_root: Path) -> dict[str, list[str]]:
    """Generates all 4 standard test dossiers under the specified target directory."""
    created_files: dict[str, list[str]] = {
        "clean_4pages": [],
        "benchmark_16pages": [],
        "degraded_page2": [],
        "corrupted": [],
    }

    # 1. Clean Dossier (Happy Path)
    dir_clean = target_root / "clean_4pages"
    dir_clean.mkdir(parents=True, exist_ok=True)

    # KYC ID (Photographic Specimen of Jane Doe)
    p_kyc_jpg = dir_clean / "kyc_executive_id.jpg"
    asset_template = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "assets" / "kyc_specimen_jane_doe.jpg"
    if not p_kyc_jpg.exists() and asset_template.exists():
        shutil.copyfile(asset_template, p_kyc_jpg)
    if p_kyc_jpg.exists():
        created_files["clean_4pages"].append(str(p_kyc_jpg))

    # Bank Statement 4-page PDF
    pdf_builder = MinimalPDFBuilder()
    for page in generate_bank_statement_pages(page_count=4):
        pdf_builder.add_page(page)
    p_stmt = dir_clean / "bank_statement_4pages.pdf"
    p_stmt.write_bytes(pdf_builder.build_bytes())
    created_files["clean_4pages"].append(str(p_stmt))

    # Tax Filing 2-page PDF
    tax_builder = MinimalPDFBuilder()
    for page in generate_tax_filing_pages():
        tax_builder.add_page(page)
    p_tax = dir_clean / "tax_filing_irs1120.pdf"
    p_tax.write_bytes(tax_builder.build_bytes())
    created_files["clean_4pages"].append(str(p_tax))

    # 2. Benchmark Dossier (16-page Heavy Statement for Concurrency Evidence)
    dir_bench = target_root / "benchmark_16pages"
    dir_bench.mkdir(parents=True, exist_ok=True)
    bench_builder = MinimalPDFBuilder()
    for page in generate_bank_statement_pages(page_count=16):
        bench_builder.add_page(page)
    p_bench = dir_bench / "bank_statement_16pages.pdf"
    p_bench.write_bytes(bench_builder.build_bytes())
    created_files["benchmark_16pages"].append(str(p_bench))

    # 3. Degraded Dossier (Page 2 OCR Failure to test Result Envelope)
    dir_deg = target_root / "degraded_page2"
    dir_deg.mkdir(parents=True, exist_ok=True)
    deg_builder = MinimalPDFBuilder()
    for page in generate_bank_statement_pages(page_count=3, degrade_page=2):
        deg_builder.add_page(page)
    p_deg = dir_deg / "bank_statement_degraded.pdf"
    p_deg.write_bytes(deg_builder.build_bytes())
    created_files["degraded_page2"].append(str(p_deg))

    # 4. Corrupted Dossier (Truncated/Corrupt PDF to test link_error)
    dir_corrupt = target_root / "corrupted"
    dir_corrupt.mkdir(parents=True, exist_ok=True)
    p_corrupt = dir_corrupt / "corrupted_statement.pdf"
    # Write invalid PDF header and truncated garbage byte stream
    p_corrupt.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\n%%FATAL_TRUNCATION_ERROR%%")
    created_files["corrupted"].append(str(p_corrupt))

    return created_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic financial dossiers for Celery workflows.")
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "tests" / "fixtures",
        help="Target fixtures directory (defaults to 02_workflows/tests/fixtures).",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    print(f"Generating synthetic financial dossiers in: {output_dir}")
    created = generate_all_fixtures(output_dir)

    total = 0
    for suite, files in created.items():
        print(f"\n[{suite}] ({len(files)} files)")
        for f in files:
            size_kb = round(os.path.getsize(f) / 1024, 2)
            print(f"  ✔ {Path(f).name} ({size_kb} KB)")
            total += 1

    print(f"\nSuccessfully generated {total} test fixtures across 4 suites.")


if __name__ == "__main__":
    main()

