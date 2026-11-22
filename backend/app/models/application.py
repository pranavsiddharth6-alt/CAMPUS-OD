"""On-Duty application models for Campus OD.

Sri Krishna Arts and Science College (SKASC)
Includes ODApplication, EventDay, and ApplicationStatusHistory.
"""
import uuid
from datetime import datetime, date
from sqlalchemy import (
    CheckConstraint,
    Column,
    String,
    Text,
    Boolean,
    DateTime,
    Date,
    Integer,
    ForeignKey,
    Enum as SQLEnum,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import relationship
from app.database.session import Base
from app.models.enums import (
    ApplicationStatus,
    EventCategory,
    DaySession,
    EventDayStatus,
)

application_status_type = ENUM(
    ApplicationStatus, name="application_status_enum", metadata=Base.metadata
)


class ODApplication(Base):
    __tablename__ = "od_applications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_number = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "OD-2026-0001"
    
    # Student who submitted
    student_id = Column(UUID(as_uuid=True), ForeignKey("student_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    
    # Department ownership follows the application, even if the student later transfers.
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), index=True)

    # Snapshot of assigned class tutor at time of submission
    assigned_tutor_id = Column(UUID(as_uuid=True), ForeignKey("tutor_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)

    # Event details
    event_name = Column(String(200), nullable=False, index=True)
    event_category = Column(SQLEnum(EventCategory, name="event_category_enum"), nullable=False)
    host_institution = Column(String(200), nullable=False)
    venue_location = Column(String(255), nullable=False)
    
    # Schedule & multi-day duration
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)
    total_days = Column(Integer, nullable=False, default=1)
    description = Column(Text, nullable=False)

    # Current lifecycle status
    status = Column(
        application_status_type,
        default=ApplicationStatus.SUBMITTED,
        nullable=False,
        index=True,
    )

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_od_application_date_order"),
        CheckConstraint("total_days > 0", name="ck_od_application_total_days_positive"),
    )

    # Relationships
    student = relationship("StudentProfile", back_populates="applications")
    assigned_tutor = relationship("TutorProfile", back_populates="assigned_applications")
    event_days = relationship("EventDay", back_populates="application", cascade="all, delete-orphan", order_by="EventDay.event_date")
    documents = relationship("ApplicationDocument", back_populates="application", cascade="all, delete-orphan")
    status_history = relationship("ApplicationStatusHistory", back_populates="application", cascade="all, delete-orphan", order_by="ApplicationStatusHistory.created_at")


class EventDay(Base):
    __tablename__ = "event_days"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("od_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    event_date = Column(Date, nullable=False, index=True)
    is_full_day = Column(Boolean, default=True, nullable=False)
    session = Column(SQLEnum(DaySession, name="day_session_enum"), default=DaySession.FULL_DAY, nullable=False)
    
    # Day-specific verification status
    day_status = Column(
        SQLEnum(EventDayStatus, name="event_day_status_enum"),
        default=EventDayStatus.PENDING,
        nullable=False,
        index=True,
    )
    verification_notes = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("application_id", "event_date", name="uq_event_day_application_date"),
    )

    application = relationship("ODApplication", back_populates="event_days")
    evidence_submissions = relationship("EvidenceSubmission", back_populates="event_day", cascade="all, delete-orphan")


class ApplicationStatusHistory(Base):
    __tablename__ = "application_status_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    application_id = Column(UUID(as_uuid=True), ForeignKey("od_applications.id", ondelete="RESTRICT"), nullable=False, index=True)
    from_status = Column(application_status_type, nullable=True)
    to_status = Column(application_status_type, nullable=False)
    changed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    hod_assignment_id = Column(UUID(as_uuid=True), ForeignKey("hod_assignments.id", ondelete="RESTRICT"))
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    application = relationship("ODApplication", back_populates="status_history")
    changed_by = relationship("User")
    hod_assignment = relationship("HODAssignment")

    @property
    def hod_name(self):
        return self.hod_assignment.full_name if self.hod_assignment else None
