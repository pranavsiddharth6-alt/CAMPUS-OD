"""Evidence, file storage metadata, and verification models for Campus OD.

Sri Krishna Arts and Science College (SKASC)
Entities: stored_files, application_documents, evidence_submissions,
location_captures, evidence_reviews.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    CheckConstraint,
    Column,
    String,
    Text,
    BigInteger,
    Float,
    DateTime,
    ForeignKey,
    Enum as SQLEnum,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.session import Base
from app.models.enums import DocumentType, EvidenceReviewStatus


class StoredFile(Base):
    __tablename__ = "stored_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    storage_key = Column(String(255), unique=True, nullable=False, index=True)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)
    sha256_checksum = Column(String(64), nullable=False, index=True)
    uploaded_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("file_size_bytes >= 0", name="ck_stored_file_size_nonnegative"),
    )

    uploader = relationship("User")


class ApplicationDocument(Base):
    __tablename__ = "application_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("od_applications.id", ondelete="RESTRICT"), nullable=False, index=True)
    stored_file_id = Column(UUID(as_uuid=True), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_type = Column(SQLEnum(DocumentType, name="document_type_enum"), nullable=False)
    notes = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    application = relationship("ODApplication", back_populates="documents")
    stored_file = relationship("StoredFile")


class EvidenceSubmission(Base):
    __tablename__ = "evidence_submissions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_day_id = Column(UUID(as_uuid=True), ForeignKey("event_days.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    # File references
    venue_photo_file_id = Column(UUID(as_uuid=True), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=True, index=True)
    organizer_proof_file_id = Column(UUID(as_uuid=True), ForeignKey("stored_files.id", ondelete="RESTRICT"), nullable=True, index=True)

    submission_notes = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=False)  # Student client time
    server_received_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    event_day = relationship("EventDay", back_populates="evidence_submissions")
    venue_photo = relationship("StoredFile", foreign_keys=[venue_photo_file_id])
    organizer_proof = relationship("StoredFile", foreign_keys=[organizer_proof_file_id])
    location_captures = relationship("LocationCapture", back_populates="evidence_submission", cascade="all, delete-orphan")
    reviews = relationship("EvidenceReview", back_populates="evidence_submission", cascade="all, delete-orphan")


class LocationCapture(Base):
    """Stores GPS data independently from venue photograph records."""
    __tablename__ = "location_captures"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evidence_submission_id = Column(UUID(as_uuid=True), ForeignKey("evidence_submissions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy_meters = Column(Float, nullable=True)
    captured_at = Column(DateTime, nullable=False)  # GPS device timestamp
    server_recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_location_latitude_range"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_location_longitude_range"),
        # Maximum finite double, equivalent to the PostgreSQL check and portable to SQLite.
        CheckConstraint(
            "accuracy_meters >= 0 AND accuracy_meters <= 1.7976931348623157e308",
            name="ck_location_accuracy_range",
        ),
    )

    evidence_submission = relationship("EvidenceSubmission", back_populates="location_captures")


class EvidenceReview(Base):
    """Tutor audit record for submitted event day proof."""
    __tablename__ = "evidence_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evidence_submission_id = Column(UUID(as_uuid=True), ForeignKey("evidence_submissions.id", ondelete="RESTRICT"), nullable=False, index=True)
    reviewed_by_tutor_id = Column(UUID(as_uuid=True), ForeignKey("tutor_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    review_status = Column(SQLEnum(EvidenceReviewStatus, name="evidence_review_status_enum"), nullable=False)
    remarks = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    evidence_submission = relationship("EvidenceSubmission", back_populates="reviews")
    reviewer = relationship("TutorProfile", back_populates="reviews")
