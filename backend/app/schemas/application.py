import uuid
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from app.models.enums import (
    ApplicationStatus,
    EventCategory,
    DaySession,
    EventDayStatus,
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
