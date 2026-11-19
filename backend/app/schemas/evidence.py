import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Optional
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from app.models.enums import ApplicationStatus, DaySession, EvidenceReviewStatus


class StoredFileResponse(BaseModel):
    id: uuid.UUID
    storage_key: str
    original_filename: str
    content_type: str
    file_size_bytes: int
    sha256_checksum: str
    created_at: datetime

    class Config:
        from_attributes = True


class LocationCaptureCreate(BaseModel):
    latitude: float
    longitude: float
    accuracy_meters: Optional[float] = None
    captured_at: datetime


class LocationCaptureResponse(LocationCaptureCreate):
    id: uuid.UUID
    evidence_submission_id: uuid.UUID
    server_recorded_at: datetime

    class Config:
        from_attributes = True


class EvidenceSubmissionResponse(BaseModel):
    id: uuid.UUID
    event_day_id: uuid.UUID
    venue_photo_file_id: Optional[uuid.UUID] = None
    organizer_proof_file_id: Optional[uuid.UUID] = None
    submission_notes: Optional[str] = None
    submitted_at: datetime
    server_received_at: datetime

    class Config:
        from_attributes = True


class EvidenceReviewCreate(BaseModel):
    review_status: EvidenceReviewStatus
    remarks: Optional[str] = None


class EvidenceReviewResponse(EvidenceReviewCreate):
    id: uuid.UUID
    evidence_submission_id: uuid.UUID
    reviewed_by_tutor_id: uuid.UUID
    reviewed_at: datetime

    class Config:
        from_attributes = True


class EvidenceGPS(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(strict=True, ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(strict=True, ge=-180, le=180, allow_inf_nan=False)
    accuracy_meters: float = Field(strict=True, ge=0, allow_inf_nan=False)
    captured_at: AwareDatetime


class EvidenceUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    gps: EvidenceGPS
    submitted_at: AwareDatetime
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""


class DayEvidenceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    review_status: EvidenceReviewStatus
    remarks: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class EvidenceFileView(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class EvidenceGPSView(BaseModel):
    latitude: float
    longitude: float
    accuracy_meters: float | None
    captured_at: datetime


class EvidenceReviewView(BaseModel):
    review_status: EvidenceReviewStatus
    remarks: str | None
    reviewed_at: datetime


class EvidenceAttemptView(BaseModel):
    id: uuid.UUID
    notes: str | None
    submitted_at: datetime
    server_received_at: datetime
    gps: EvidenceGPSView | None
    venue_photo: EvidenceFileView | None
    organizer_proof: EvidenceFileView | None
    reviews: list[EvidenceReviewView]


class EventDayEvidenceView(BaseModel):
    id: uuid.UUID
    event_date: date
    session: DaySession
    state: Literal["NOT_SUBMITTED", "AWAITING_REVIEW", "CORRECTION_REQUIRED", "VERIFIED", "REJECTED"]
    attempts: list[EvidenceAttemptView]


class ApplicationEvidenceView(BaseModel):
    status: ApplicationStatus
    days: list[EventDayEvidenceView]
