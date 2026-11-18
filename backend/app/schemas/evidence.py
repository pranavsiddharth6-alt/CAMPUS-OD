import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from app.models.enums import DocumentType, EvidenceReviewStatus


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
