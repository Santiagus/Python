"""SQLAlchemy ORM models for commercial credit applications, documents, pages, and memos."""

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""

    pass


class ApplicationStatus(StrEnum):
    """Lifecycle states for a commercial credit application."""

    PENDING = "pending"
    VALIDATING = "validating"
    PROCESSING = "processing"
    APPROVED = "approved"
    DECLINED = "declined"
    MANUAL_REVIEW = "manual_review"
    FAILED = "failed"


class DocumentType(StrEnum):
    """Permitted dossier document categories."""

    KYC_ID = "kyc_id"
    BANK_STATEMENT = "bank_statement"
    TAX_FILING = "tax_filing"


class DocumentStatus(StrEnum):
    """Processing states for ingested dossier documents."""

    UPLOADED = "uploaded"
    VALIDATING = "validating"
    PROCESSED = "processed"
    DEGRADED = "degraded"
    FAILED = "failed"


class PageStatus(StrEnum):
    """Processing states for individual partitioned document pages."""

    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    DEGRADED = "degraded"
    FAILED = "failed"


class DecisionType(StrEnum):
    """Underwriting outcome categories."""

    APPROVED = "approved"
    DECLINED = "declined"
    MANUAL_REVIEW = "manual_review"


class Application(Base):
    """Commercial credit facility application entity."""

    __tablename__ = "applications"
    __table_args__ = (
        CheckConstraint("requested_facility > 0", name="applications_requested_facility_positive"),
        Index("idx_applications_status", "status"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    applicant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_facility: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ApplicationStatus.PENDING, nullable=False)
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=func.now(),
    )

    # Relationships
    documents: Mapped[list["Document"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="Document.created_at",
        lazy="selectin",
    )
    underwriting_memo: Mapped["UnderwritingMemo | None"] = relationship(
        back_populates="application",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Application with python-side defaults."""
        kwargs.setdefault("id", uuid4())
        kwargs.setdefault("status", ApplicationStatus.PENDING)
        kwargs.setdefault("underwriting_memo", None)
        kwargs.setdefault("documents", [])
        now = datetime.now(timezone.utc)
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        super().__init__(**kwargs)

    @property
    def application_id(self) -> str:
        """String representation of the application UUID for API schemas."""
        return str(self.id)


class Document(Base):
    """Ingested dossier document (e.g. KYC ID, Bank Statement, Tax Return)."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("file_size_bytes >= 0", name="documents_file_size_non_negative"),
        Index("idx_documents_application_id", "application_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=DocumentStatus.UPLOADED, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=func.now(),
    )

    # Relationships
    application: Mapped[Application] = relationship(back_populates="documents")
    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentPage.page_number",
        lazy="selectin",
    )

    def __init__(self, **kwargs: Any) -> None:
        """Initialize Document with python-side defaults."""
        kwargs.setdefault("id", uuid4())
        kwargs.setdefault("status", DocumentStatus.UPLOADED)
        kwargs.setdefault("metadata_", {})
        kwargs.setdefault("pages", [])
        now = datetime.now(timezone.utc)
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        super().__init__(**kwargs)


class DocumentPage(Base):
    """Partitioned document page processed in parallel chord headers."""

    __tablename__ = "document_pages"
    __table_args__ = (
        CheckConstraint("page_number > 0", name="document_pages_page_number_positive"),
        CheckConstraint(
            "ocr_confidence >= 0.0 AND ocr_confidence <= 1.0",
            name="document_pages_ocr_confidence_range",
        ),
        UniqueConstraint("document_id", "page_number", name="document_pages_document_id_page_number_key"),
        Index("idx_document_pages_document_id", "document_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=PageStatus.PENDING, nullable=False)
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=func.now(),
    )

    # Relationships
    document: Mapped[Document] = relationship(back_populates="pages")

    def __init__(self, **kwargs: Any) -> None:
        """Initialize DocumentPage with python-side defaults."""
        kwargs.setdefault("id", uuid4())
        kwargs.setdefault("status", PageStatus.PENDING)
        kwargs.setdefault("metrics", {})
        now = datetime.now(timezone.utc)
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        super().__init__(**kwargs)


class UnderwritingMemo(Base):
    """Aggregated underwriting decision memo compiled after Celery chord fan-in."""

    __tablename__ = "underwriting_memos"
    __table_args__ = (
        Index("idx_underwriting_memos_application_id", "application_id"),
        Index("idx_underwriting_memos_decision", "decision"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    calculated_dscr: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    net_cashflow: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_revenue: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    audit_flags: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    stage_timings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=func.now(),
    )

    # Relationships
    application: Mapped[Application] = relationship(back_populates="underwriting_memo")

    def __init__(self, **kwargs: Any) -> None:
        """Initialize UnderwritingMemo with python-side defaults."""
        kwargs.setdefault("id", uuid4())
        kwargs.setdefault("audit_flags", [])
        kwargs.setdefault("stage_timings", {})
        now = datetime.now(timezone.utc)
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        super().__init__(**kwargs)
