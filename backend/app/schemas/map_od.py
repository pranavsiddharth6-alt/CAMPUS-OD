from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from app.schemas.application import Coordinates

LocationResult = Literal["PASSED", "OUTSIDE_BOUNDARY", "POOR_ACCURACY", "OUTSIDE_AND_POOR_ACCURACY"]


class CaptureRequest(Coordinates):
    request_id: UUID
    accuracy_meters: float = Field(strict=True, gt=0, allow_inf_nan=False)
    captured_at: AwareDatetime | None = None


class CaptureView(Coordinates):
    id: UUID
    accuracy_meters: float
    captured_at: datetime | None
    server_recorded_at: datetime
    distance_metres: float
    allowed_radius_metres: float
    allowed_accuracy_metres: float
    result: LocationResult


class MapDay(BaseModel):
    id: UUID
    event_date: date
    can_capture: bool
    selected_capture_id: UUID | None
    attached_capture_id: UUID | None
    attempts: list[CaptureView]


class MapODView(BaseModel):
    venue_name: str
    expected_venue: Coordinates | None
    today_ist: date
    radius_metres: float
    max_accuracy_metres: float
    received_capture_id: UUID | None = None
    days: list[MapDay]
