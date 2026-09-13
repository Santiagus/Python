"""Unit tests for SQLAlchemy models, enums, relationships, and Pydantic schemas."""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

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
from app.schemas import (
    ApplicationCreate,
    ApplicationResponse,
    DossierSubmitRequest,
    UnderwritingDecisionSummary,
)


class TestModelDefinitions:
    """Unit tests verifying ORM model initialization, defaults, and properties."""

    def test_application_initialization_and_properties(self) -> None:
        """Verify Application instantiates with proper defaults and application_id property."""
        app_id = uuid4()
        app = Application(
            id=app_id,
            company_name="Apex Fintech Dynamics Inc.",
            applicant_name="JANE DOE",
            requested_facility=Decimal("250000.00"),
        )
        assert app.id == app_id
        assert app.application_id == str(app_id)
        assert app.status == ApplicationStatus.PENDING
        assert app.company_name == "Apex Fintech Dynamics Inc."
        assert app.applicant_name == "JANE DOE"
        assert app.requested_facility == Decimal("250000.00")
        assert app.workflow_id is None
        assert app.error_message is None

    def test_document_initialization_and_defaults(self) -> None:
        """Verify Document instantiates with proper defaults and status."""
        doc_id = uuid4()
        app_id = uuid4()
        doc = Document(
            id=doc_id,
            application_id=app_id,
            doc_type="bank_statement",
            file_path="/tmp/test.pdf",
            file_name="test.pdf",
            file_size_bytes=1024,
        )
        assert doc.id == doc_id
        assert doc.application_id == app_id
        assert doc.doc_type == "bank_statement"
        assert doc.status == DocumentStatus.UPLOADED
        assert doc.metadata_ == {}

    def test_document_page_initialization(self) -> None:
        """Verify DocumentPage instantiates with correct defaults and confidence range."""
        doc_id = uuid4()
        page = DocumentPage(
            document_id=doc_id,
            page_number=1,
            ocr_confidence=Decimal("0.9850"),
            extracted_text="Sample bank ledger line items",
        )
        assert page.document_id == doc_id
        assert page.page_number == 1
        assert page.status == PageStatus.PENDING
        assert page.ocr_confidence == Decimal("0.9850")
        assert page.metrics == {}

    def test_underwriting_memo_initialization(self) -> None:
        """Verify UnderwritingMemo model holds calculated metrics and audit flags."""
        app_id = uuid4()
        memo = UnderwritingMemo(
            application_id=app_id,
            decision=DecisionType.APPROVED,
            calculated_dscr=Decimal("1.850"),
            net_cashflow=Decimal("32549.50"),
            total_revenue=Decimal("1450000.00"),
            audit_flags=["identity_verified", "dscr_threshold_met"],
            summary="Underwriting memo compiled successfully",
            stage_timings={"total_pipeline_ms": 395.7},
        )
        assert memo.application_id == app_id
        assert memo.decision == "approved"
        assert memo.calculated_dscr == Decimal("1.850")
        assert memo.net_cashflow == Decimal("32549.50")
        assert len(memo.audit_flags) == 2
        assert memo.stage_timings["total_pipeline_ms"] == 395.7

    def test_application_relationships_in_memory(self) -> None:
        """Verify bidirectional relationships between Application, Document, and Memo."""
        app = Application(
            company_name="Apex Fintech",
            applicant_name="JANE DOE",
            requested_facility=Decimal("100000.00"),
        )
        doc1 = Document(
            doc_type="kyc_id",
            file_path="/path/kyc.jpg",
            file_name="kyc.jpg",
            file_size_bytes=5000,
            application=app,
        )
        doc2 = Document(
            doc_type="bank_statement",
            file_path="/path/stmt.pdf",
            file_name="stmt.pdf",
            file_size_bytes=15000,
            application=app,
        )
        memo = UnderwritingMemo(
            decision=DecisionType.APPROVED,
            summary="Auto-approved",
            application=app,
        )
        assert len(app.documents) == 2
        assert app.underwriting_memo is memo
        assert doc1.application is app


class TestSchemaSerialization:
    """Unit tests for Pydantic schema validation and ORM serialization."""

    def test_application_create_validation(self) -> None:
        """ApplicationCreate must reject zero or negative requested facility."""
        with pytest.raises(ValidationError):
            ApplicationCreate(
                company_name="Bad Corp",
                applicant_name="Test",
                requested_facility=-100.0,
            )

        with pytest.raises(ValidationError):
            ApplicationCreate(
                company_name="Bad Corp",
                applicant_name="Test",
                requested_facility=0.0,
            )

        valid = ApplicationCreate(
            company_name="Valid Corp",
            applicant_name="John Doe",
            requested_facility=50000.0,
        )
        assert valid.requested_facility == 50000.0

    def test_application_response_from_orm(self) -> None:
        """ApplicationResponse must serialize an Application ORM model with nested memo."""
        app_id = uuid4()
        memo = UnderwritingMemo(
            id=uuid4(),
            application_id=app_id,
            decision="approved",
            calculated_dscr=Decimal("1.85"),
            net_cashflow=Decimal("32549.50"),
            total_revenue=Decimal("1450000.00"),
            audit_flags=["clean_record"],
            summary="Underwriting passed.",
        )
        app = Application(
            id=app_id,
            company_name="Apex Corp",
            applicant_name="Jane Doe",
            requested_facility=Decimal("250000.00"),
            status=ApplicationStatus.APPROVED,
            workflow_id="wf-12345",
            underwriting_memo=memo,
        )

        response_schema = ApplicationResponse.model_validate(app)
        assert response_schema.application_id == str(app_id)
        assert response_schema.company_name == "Apex Corp"
        assert response_schema.requested_facility == 250000.00
        assert response_schema.status == "approved"
        assert response_schema.workflow_id == "wf-12345"
        assert response_schema.underwriting_memo is not None
        assert response_schema.underwriting_memo.decision == "approved"
        assert response_schema.underwriting_memo.calculated_dscr == 1.85
        assert response_schema.underwriting_memo.net_cashflow == 32549.50
        assert response_schema.underwriting_memo.total_revenue == 1450000.00
        assert response_schema.underwriting_memo.audit_flags == ["clean_record"]

    def test_dossier_submit_request_validation(self) -> None:
        """DossierSubmitRequest must validate manifest structure."""
        req = DossierSubmitRequest(
            manifest={"bank_statement": "/tmp/stmt.pdf", "kyc_id": "/tmp/kyc.jpg"}
        )
        assert len(req.manifest) == 2
        assert req.manifest["bank_statement"] == "/tmp/stmt.pdf"

