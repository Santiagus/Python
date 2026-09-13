"""Integration tests verifying PostgreSQL schema, constraints, triggers, and ORM persistence."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Application,
    ApplicationStatus,
    DecisionType,
    Document,
    DocumentPage,
    DocumentStatus,
    PageStatus,
    UnderwritingMemo,
)


@pytest.mark.asyncio
class TestDatabaseIntegration:
    """Integration test suite executing against the PostgreSQL testcontainer."""

    async def test_application_crud_persistence(self, db_session: AsyncSession) -> None:
        """Verify Application entity persistence, retrieval, and status update."""
        app = Application(
            company_name="Apex Fintech Dynamics Inc.",
            applicant_name="JANE DOE",
            requested_facility=Decimal("500000.00"),
            status=ApplicationStatus.PENDING,
        )
        db_session.add(app)
        await db_session.commit()
        await db_session.refresh(app)

        assert app.id is not None
        assert app.created_at is not None
        assert app.updated_at is not None

        # Query back from DB
        stmt = select(Application).where(Application.id == app.id)
        result = await db_session.execute(stmt)
        fetched_app = result.scalar_one()

        assert fetched_app.company_name == "Apex Fintech Dynamics Inc."
        assert fetched_app.requested_facility == Decimal("500000.00")
        assert fetched_app.status == ApplicationStatus.PENDING

        # Update status
        fetched_app.status = ApplicationStatus.PROCESSING
        fetched_app.workflow_id = "wf-test-1234"
        await db_session.commit()
        await db_session.refresh(fetched_app)

        assert fetched_app.status == ApplicationStatus.PROCESSING
        assert fetched_app.workflow_id == "wf-test-1234"

    async def test_documents_and_pages_cascade_delete(self, db_session: AsyncSession) -> None:
        """Verify documents and document pages are deleted when application is deleted."""
        app = Application(
            company_name="Solvent Enterprises LLC",
            applicant_name="ROBERT SMITH",
            requested_facility=Decimal("150000.00"),
        )
        db_session.add(app)
        await db_session.flush()

        doc = Document(
            application_id=app.id,
            doc_type="bank_statement",
            file_path="/data/stmt.pdf",
            file_name="stmt.pdf",
            file_size_bytes=24500,
            status=DocumentStatus.PROCESSED,
        )
        db_session.add(doc)
        await db_session.flush()

        page1 = DocumentPage(
            document_id=doc.id,
            page_number=1,
            status=PageStatus.PROCESSED,
            ocr_confidence=Decimal("0.9850"),
            extracted_text="Page 1 statement transactions",
        )
        page2 = DocumentPage(
            document_id=doc.id,
            page_number=2,
            status=PageStatus.PROCESSED,
            ocr_confidence=Decimal("0.9620"),
            extracted_text="Page 2 statement transactions",
        )
        db_session.add_all([page1, page2])
        await db_session.commit()

        # Verify records exist
        doc_stmt = select(Document).where(Document.application_id == app.id)
        docs = (await db_session.execute(doc_stmt)).scalars().all()
        assert len(docs) == 1

        pages_stmt = select(DocumentPage).where(DocumentPage.document_id == doc.id)
        pages = (await db_session.execute(pages_stmt)).scalars().all()
        assert len(pages) == 2

        # Delete application
        await db_session.delete(app)
        await db_session.commit()

        # Verify cascade deletion
        remaining_docs = (await db_session.execute(doc_stmt)).scalars().all()
        remaining_pages = (await db_session.execute(pages_stmt)).scalars().all()
        assert len(remaining_docs) == 0
        assert len(remaining_pages) == 0

    async def test_underwriting_memo_persistence_and_relationship(
        self, db_session: AsyncSession
    ) -> None:
        """Verify UnderwritingMemo 1-to-1 relationship and eager loading."""
        app = Application(
            company_name="Apex Global Corp",
            applicant_name="ALICE WONG",
            requested_facility=Decimal("750000.00"),
            status=ApplicationStatus.APPROVED,
        )
        db_session.add(app)
        await db_session.flush()

        app_id = app.id
        memo = UnderwritingMemo(
            application_id=app_id,
            decision=DecisionType.APPROVED,
            calculated_dscr=Decimal("2.150"),
            net_cashflow=Decimal("85000.00"),
            total_revenue=Decimal("2500000.00"),
            audit_flags=["identity_verified", "dscr_satisfied"],
            summary="Application fully approved with strong debt coverage.",
            stage_timings={
                "stage_1_validation_ms": 30.5,
                "stage_2_fanout_chord_ms": 280.0,
                "stage_3_fanin_aggregation_ms": 25.1,
                "total_pipeline_ms": 335.6,
            },
        )
        db_session.add(memo)
        await db_session.commit()
        db_session.expunge_all()

        # Query with selectinload to verify DB persistence and deserialization
        stmt = (
            select(Application)
            .options(selectinload(Application.underwriting_memo))
            .where(Application.id == app_id)
        )
        result = await db_session.execute(stmt)
        loaded_app = result.scalar_one()

        assert loaded_app.underwriting_memo is not None
        assert loaded_app.underwriting_memo.decision == "approved"
        assert loaded_app.underwriting_memo.calculated_dscr == Decimal("2.150")
        assert loaded_app.underwriting_memo.audit_flags == ["identity_verified", "dscr_satisfied"]
        assert loaded_app.underwriting_memo.stage_timings["total_pipeline_ms"] == 335.6

    async def test_application_facility_positive_constraint(self, db_session: AsyncSession) -> None:
        """Verify database enforces check constraint on requested_facility > 0."""
        app = Application(
            company_name="Invalid Negative Facility Inc.",
            applicant_name="TEST USER",
            requested_facility=Decimal("-100.00"),
        )
        db_session.add(app)
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_document_page_ocr_confidence_constraint(self, db_session: AsyncSession) -> None:
        """Verify database enforces ocr_confidence range between 0.0 and 1.0."""
        app = Application(
            company_name="Test Constraints Co.",
            applicant_name="TEST USER",
            requested_facility=Decimal("10000.00"),
        )
        db_session.add(app)
        await db_session.flush()

        doc = Document(
            application_id=app.id,
            doc_type="kyc_id",
            file_path="/tmp/id.jpg",
            file_name="id.jpg",
            file_size_bytes=500,
        )
        db_session.add(doc)
        await db_session.flush()

        page_invalid = DocumentPage(
            document_id=doc.id,
            page_number=1,
            ocr_confidence=Decimal("1.5000"),  # > 1.0 violates constraint
        )
        db_session.add(page_invalid)
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_updated_at_trigger(self, db_session: AsyncSession) -> None:
        """Verify update_timestamp() trigger automatically updates updated_at column."""
        app = Application(
            company_name="Trigger Test Ltd.",
            applicant_name="JANE DOE",
            requested_facility=Decimal("200000.00"),
        )
        db_session.add(app)
        await db_session.commit()
        await db_session.refresh(app)

        initial_updated_at = app.updated_at

        # Sleep briefly to ensure clock ticks
        await asyncio.sleep(0.05)

        app.company_name = "Trigger Test Ltd. Renamed"
        await db_session.commit()
        await db_session.refresh(app)

        assert app.updated_at > initial_updated_at
