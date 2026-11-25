"""Store and verify independent GPS captures for approved event days."""

from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.application import EventDay, ODApplication
from app.models.enums import ApplicationStatus, UserRole
from app.models.evidence import EvidenceSubmission, LocationCapture
from app.schemas.application import Coordinates
from app.schemas.map_od import CaptureRequest, CaptureView, MapDay, MapODView
from app.services.od_applications import PARTICIPATION_OPEN_STATUSES, _scope, expected_venue
from app.services.private_uploads import ApplicationError

IST = ZoneInfo("Asia/Kolkata")
EARTH_RADIUS_METRES = 6_371_008.8
_READ_STATUSES = PARTICIPATION_OPEN_STATUSES | {
    ApplicationStatus.UNDER_HOD_REVIEW, ApplicationStatus.OD_FINALIZED,
    ApplicationStatus.REJECTED, ApplicationStatus.HOD_CORRECTION_REQUESTED,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def haversine_metres(venue: Coordinates, location: Coordinates) -> float:
    a_lat, b_lat = radians(venue.latitude), radians(location.latitude)
    delta_lat = b_lat - a_lat
    delta_lon = radians(location.longitude - venue.longitude)
    haversine = sin(delta_lat / 2) ** 2 + cos(a_lat) * cos(b_lat) * sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_METRES * asin(sqrt(min(1.0, max(0.0, haversine))))


def verify_location(distance: float, accuracy: float, radius: float, max_accuracy: float) -> str:
    outside = distance > radius
    poor_accuracy = accuracy > max_accuracy
    if outside and poor_accuracy:
        return "OUTSIDE_AND_POOR_ACCURACY"
    if outside:
        return "OUTSIDE_BOUNDARY"
    if poor_accuracy:
        return "POOR_ACCURACY"
    return "PASSED"


def location_draft(day: EventDay) -> EvidenceSubmission | None:
    return next((item for item in day.evidence_submissions if item.is_location_draft), None)


def capture_attempts(day: EventDay) -> list[LocationCapture]:
    draft = location_draft(day)
    return sorted(draft.location_captures, key=lambda row: (row.server_recorded_at, row.id)) if draft else []


def selected_capture(attempts: list[LocationCapture]) -> LocationCapture | None:
    return next((row for row in reversed(attempts) if row.verification_result == "PASSED"),
                attempts[-1] if attempts else None)


def _load(db, application_id, user, *, lock=False):
    query = select(ODApplication).where(
        ODApplication.id == application_id, _scope(user),
    ).options(selectinload(ODApplication.event_days).selectinload(EventDay.evidence_submissions)
              .selectinload(EvidenceSubmission.location_captures))
    application = db.scalar(query.with_for_update() if lock else query)
    if application is None:
        raise ApplicationError(404, "Application not found.")
    return application


def _capture_view(row: LocationCapture) -> CaptureView:
    return CaptureView(
        id=row.id, latitude=row.latitude, longitude=row.longitude, accuracy_meters=row.accuracy_meters,
        captured_at=row.captured_at.replace(tzinfo=timezone.utc) if row.browser_time_present else None,
        server_recorded_at=row.server_recorded_at.replace(tzinfo=timezone.utc),
        distance_metres=row.distance_metres, allowed_radius_metres=row.allowed_radius_metres,
        allowed_accuracy_metres=row.allowed_accuracy_metres, result=row.verification_result,
    )


def _view(app, user, now, *, received_capture_id=None):
    local_date = now.astimezone(IST).date()
    venue = expected_venue(app)
    open_for_capture = user.role == UserRole.STUDENT and app.status in PARTICIPATION_OPEN_STATUSES and venue is not None
    days = []
    for day in app.event_days:
        attempts = capture_attempts(day)
        selected = selected_capture(attempts)
        submitted = max((item for item in day.evidence_submissions if not item.is_location_draft),
                        key=lambda row: (row.server_received_at, row.id), default=None)
        days.append(MapDay(
            id=day.id, event_date=day.event_date,
            can_capture=open_for_capture and day.event_date == local_date,
            selected_capture_id=selected.id if selected else None,
            attached_capture_id=submitted.map_capture_id if submitted else None,
            attempts=[_capture_view(row) for row in attempts],
        ))
    return MapODView(
        venue_name=app.venue_location, expected_venue=venue, today_ist=local_date, days=days,
        radius_metres=settings.MAP_OD_RADIUS_METRES, max_accuracy_metres=settings.MAP_OD_MAX_ACCURACY_METRES,
        received_capture_id=received_capture_id,
    )


class MapODService:
    def __init__(self, sessions, _storage):
        self._sessions = sessions

    def detail(self, user, application_id: UUID) -> MapODView:
        with self._sessions() as db:
            app = _load(db, application_id, user)
            if app.status not in _READ_STATUSES:
                raise ApplicationError(409, "Map OD requires approved Prior OD.")
            if app.status == ApplicationStatus.REJECTED and not any(location_draft(day) for day in app.event_days):
                raise ApplicationError(409, "Map OD requires approved Prior OD.")
            return _view(app, user, utc_now())

    def capture(self, user, application_id: UUID, day_id: UUID, request: CaptureRequest,
                received_at: datetime) -> MapODView:
        if user.role != UserRole.STUDENT:
            raise ApplicationError(403, "Insufficient permissions.")
        with self._sessions.begin() as db:
            app = _load(db, application_id, user, lock=True)
            if app.status not in PARTICIPATION_OPEN_STATUSES:
                raise ApplicationError(409, "Map OD requires approved Prior OD and an open evidence stage.")
            day = next((item for item in app.event_days if item.id == day_id), None)
            if day is None:
                raise ApplicationError(404, "Event day not found.")
            venue = expected_venue(app)
            if venue is None:
                raise ApplicationError(409, "Map OD verification is unavailable for this legacy application.")
            if received_at.astimezone(IST).date() != day.event_date:
                raise ApplicationError(409, "Capture is available only on the selected event date in IST.")

            draft = location_draft(day)
            recorded_at = received_at.astimezone(timezone.utc).replace(tzinfo=None)
            client_time = request.captured_at.astimezone(timezone.utc).replace(tzinfo=None) if request.captured_at else None
            request_key = str(request.request_id)
            existing = db.scalar(select(LocationCapture).where(LocationCapture.request_key == request_key))
            if existing is not None:
                if (draft is None or existing.evidence_submission_id != draft.id
                        or (existing.latitude, existing.longitude, existing.accuracy_meters,
                            existing.captured_at if existing.browser_time_present else None)
                        != (request.latitude, request.longitude, request.accuracy_meters, client_time)):
                    raise ApplicationError(409, "This capture request was already used.")
                return _view(app, user, received_at, received_capture_id=existing.id)
            if draft is None:
                draft = EvidenceSubmission(is_location_draft=True, submitted_at=recorded_at,
                                           server_received_at=recorded_at)
                day.evidence_submissions.append(draft)
            distance = haversine_metres(venue, request)
            radius, accuracy = settings.MAP_OD_RADIUS_METRES, settings.MAP_OD_MAX_ACCURACY_METRES
            capture = LocationCapture(
                request_key=request_key, latitude=request.latitude, longitude=request.longitude,
                accuracy_meters=request.accuracy_meters, captured_at=client_time or recorded_at,
                browser_time_present=client_time is not None, server_recorded_at=recorded_at,
                distance_metres=distance, allowed_radius_metres=radius, allowed_accuracy_metres=accuracy,
                verification_result=verify_location(distance, request.accuracy_meters, radius, accuracy),
            )
            draft.location_captures.append(capture)
            try:
                db.flush()
            except IntegrityError:
                raise ApplicationError(409, "This capture request could not be saved. Refresh and try again.") from None
            return _view(app, user, received_at, received_capture_id=capture.id)
