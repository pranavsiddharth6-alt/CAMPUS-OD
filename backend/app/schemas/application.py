import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Optional, List
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from app.models.enums import (
    ApplicationStatus,
    EventCategory,
    DaySession,
    EventDayStatus,
    DocumentType,
)


class EventDayCreate(BaseModel):
    event_date: date
    is_full_day: bool = True
    session: DaySession = DaySession.FULL_DAY


class EventDayResponse(EventDayCreate):
    id: uuid.UUID
    application_id: uuid.UUID
    day_status: EventDayStatus
    verification_notes: Optional[str] = None

    class Config:
        from_attributes = True


class ODApplicationCreate(BaseModel):
    event_name: str = Field(..., max_length=200)
    event_category: EventCategory
    host_institution: str = Field(..., max_length=200)
    venue_location: str = Field(..., max_length=255)
    start_date: date
    end_date: date
    description: str
    event_days: List[EventDayCreate]


class ODApplicationResponse(BaseModel):
    id: uuid.UUID
    application_number: str
    student_id: uuid.UUID
    assigned_tutor_id: uuid.UUID
    event_name: str
    event_category: EventCategory
    host_institution: str
    venue_location: str
    start_date: date
    end_date: date
    total_days: int
    description: str
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime
    event_days: List[EventDayResponse] = []

    class Config:
        from_attributes = True


class StatusHistoryResponse(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    from_status: Optional[ApplicationStatus] = None
    to_status: ApplicationStatus
    changed_by_user_id: uuid.UUID
    remarks: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SubmissionDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_date: date
    session: DaySession = DaySession.FULL_DAY


class Coordinates(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    latitude: float = Field(strict=True, ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(strict=True, ge=-180, le=180, allow_inf_nan=False)


class ApplicationSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    event_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    event_category: EventCategory
    host_institution: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    venue_location: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)]
    event_days: list[SubmissionDay] = Field(min_length=1)
    expected_venue: Coordinates | None = None

    @model_validator(mode="after")
    def unique_event_dates(self):
        if len({day.event_date for day in self.event_days}) != len(self.event_days):
            raise ValueError("Event dates must be distinct.")
        return self


class PriorODSubmission(ApplicationSubmission):
    expected_venue: Coordinates


class ApplicationCorrection(ApplicationSubmission):
    expected_revision: uuid.UUID | None


class TutorDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    action: Literal["PREAPPROVE", "REJECT", "REQUEST_CORRECTION"]
    remarks: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    expected_revision: uuid.UUID | None


class HODDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    action: Literal["APPROVE", "REJECT", "REQUEST_CORRECTION"]
    remarks: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    expected_revision: uuid.UUID

    @model_validator(mode="after")
    def require_remarks(self):
        if self.action != "APPROVE" and not self.remarks:
            raise ValueError("Remarks are required for rejection and correction.")
        return self


class ApplicationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_number: str
    student_name: str
    student_roll_number: str
    tutor_name: str
    event_name: str
    event_category: EventCategory
    venue_location: str
    start_date: date
    end_date: date
    total_days: int
    status: ApplicationStatus
    post_od_eligible: bool


class ApplicationDocumentResponse(BaseModel):
    id: uuid.UUID
    document_type: DocumentType
    filename: str


class ApplicationHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    remarks: str | None
    created_at: datetime
    hod_name: str | None = None


class ApplicationOverview(ApplicationSummary):
    host_institution: str
    description: str
    event_days: list[SubmissionDay]
    history: list[ApplicationHistoryEntry]


class ApplicationDetail(ApplicationOverview):
    expected_venue: Coordinates | None = None
    documents: list[ApplicationDocumentResponse]
    revision: uuid.UUID | None
