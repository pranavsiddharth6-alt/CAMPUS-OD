"""Per-day participation evidence and final review for existing OD applications."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload, sessionmaker

from app.dependencies.auth import AuthenticatedUser
from app.models.academic import HODAssignment
from app.models.application import EventDay, ODApplication
from app.models.user import User
from app.models.enums import ApplicationStatus, EventDayStatus, EvidenceReviewStatus, UserRole
from app.models.evidence import EvidenceReview, EvidenceSubmission, LocationCapture, StoredFile
from app.schemas.application import ApplicationDetail, HODDecision
from app.schemas.evidence import (
    ApplicationEvidenceView, DayEvidenceDecision, EventDayEvidenceView, EvidenceAttemptView, EvidenceFileView,
    EvidenceGPSView, EvidenceReviewView, EvidenceUploadRequest,
)
from app.services.od_applications import (
    _active_hod_assignment, _check_revision, _detail, _load as _load_application, _scope, _transition,
)
from app.services.private_uploads import ApplicationError, PrivateUpload, read_upload, store_upload, write_with_uploads
from app.services.storage import LocalStorageService

_OPEN_STATUSES = {
    ApplicationStatus.PRE_APPROVED,
    ApplicationStatus.AWAITING_PARTICIPATION_PROOF,
    ApplicationStatus.UNDER_FINAL_VERIFICATION,
    ApplicationStatus.UNDER_TUTOR_CORRECTION_REVIEW,
}


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _attempts(day: EventDay) -> list[EvidenceSubmission]:
    return sorted(day.evidence_submissions, key=lambda item: (item.server_received_at, item.id))


def _reviews(attempt: EvidenceSubmission) -> list[EvidenceReview]:
    return sorted(attempt.reviews, key=lambda item: (item.reviewed_at, item.id))


def _complete(attempt: EvidenceSubmission) -> bool:
    return bool(attempt.venue_photo and attempt.organizer_proof and len(attempt.location_captures) == 1
                and attempt.location_captures[0].accuracy_meters is not None)


def _day_state(day: EventDay):
    attempts = _attempts(day)
    if not attempts:
        return "NOT_SUBMITTED"
    latest = attempts[-1]
    reviews = _reviews(latest)
    if not reviews:
        return "AWAITING_REVIEW"
    status = reviews[-1].review_status
    if status == EvidenceReviewStatus.APPROVED and _complete(latest):
        return "VERIFIED"
    if status == EvidenceReviewStatus.REJECTED:
        return "REJECTED"
    return "CORRECTION_REQUIRED"


def all_days_verified(app: ODApplication) -> bool:
    return len(app.event_days) == app.total_days > 0 and all(_day_state(day) == "VERIFIED" for day in app.event_days)


def _app_state(app: ODApplication, user: AuthenticatedUser) -> None:
    if app.status == ApplicationStatus.UNDER_TUTOR_CORRECTION_REVIEW:
        return  # Corrected applications require an explicit tutor decision to return to the HOD.
    states = [_day_state(day) for day in app.event_days]
    if all_days_verified(app):
        _transition(app, ApplicationStatus.UNDER_HOD_REVIEW, user,
                    "The tutor verified every event day and forwarded the application for HOD review.")
        return
    elif states and all(state in {"VERIFIED", "REJECTED"} for state in states):
        target = ApplicationStatus.REJECTED
    elif "AWAITING_REVIEW" in states:
        target = ApplicationStatus.UNDER_FINAL_VERIFICATION
    else:
        target = ApplicationStatus.AWAITING_PARTICIPATION_PROOF
    if app.status != target:
        _transition(app, target, user)


def _load(
    db: Session, application_id: UUID, user: AuthenticatedUser, *, lock: bool = False,
) -> ODApplication:
    # A decision must lock by department before checking the latest status and history.
    query = select(ODApplication).where(
        ODApplication.id == application_id, _scope(user, hod_review_only=not lock),
    ).options(
        selectinload(ODApplication.status_history),
        selectinload(ODApplication.event_days).selectinload(EventDay.evidence_submissions).options(
            joinedload(EvidenceSubmission.venue_photo), joinedload(EvidenceSubmission.organizer_proof),
            selectinload(EvidenceSubmission.location_captures), selectinload(EvidenceSubmission.reviews),
        ),
    )
    app = db.scalar(query.with_for_update() if lock else query)
    if app is None:
        raise ApplicationError(404, "Application not found.")
    return app


def _day(app: ODApplication, day_id: UUID) -> EventDay:
    event_day = next((day for day in app.event_days if day.id == day_id), None)
    if event_day is None:
        raise ApplicationError(404, "Event day not found.")
    if app.status not in _OPEN_STATUSES:
        raise ApplicationError(409, "This application is not open for participation evidence.")
    return event_day


def _file_view(file: StoredFile | None) -> EvidenceFileView | None:
    if file is None:
        return None
    return EvidenceFileView(filename=file.original_filename, content_type=file.content_type, size_bytes=file.file_size_bytes)


def _attempt_view(attempt: EvidenceSubmission) -> EvidenceAttemptView:
    location = attempt.location_captures[0] if len(attempt.location_captures) == 1 else None
    return EvidenceAttemptView(
        id=attempt.id, notes=attempt.submission_notes,
        submitted_at=attempt.submitted_at.replace(tzinfo=timezone.utc),
        server_received_at=attempt.server_received_at.replace(tzinfo=timezone.utc),
        gps=EvidenceGPSView(latitude=location.latitude, longitude=location.longitude,
                            accuracy_meters=location.accuracy_meters,
                            captured_at=location.captured_at.replace(tzinfo=timezone.utc)) if location else None,
        venue_photo=_file_view(attempt.venue_photo), organizer_proof=_file_view(attempt.organizer_proof),
        reviews=[EvidenceReviewView(review_status=review.review_status, remarks=review.remarks,
                                    reviewed_at=review.reviewed_at.replace(tzinfo=timezone.utc))
                 for review in _reviews(attempt)],
    )


def _view(app: ODApplication) -> ApplicationEvidenceView:
    return ApplicationEvidenceView(status=app.status, days=[
        EventDayEvidenceView(
            id=day.id, event_date=day.event_date, session=day.session, state=_day_state(day),
            attempts=[_attempt_view(attempt) for attempt in _attempts(day)],
        ) for day in app.event_days
    ])


class ODEvidenceService:
    def __init__(self, sessions: sessionmaker[Session], storage: LocalStorageService):
        self._sessions = sessions
        self._storage = storage

    def detail(self, user: AuthenticatedUser, application_id: UUID) -> ApplicationEvidenceView:
        with self._sessions() as db:
            return _view(_load(db, application_id, user))

    def submit(
        self, user: AuthenticatedUser, application_id: UUID, day_id: UUID, data: EvidenceUploadRequest,
        venue_photo: PrivateUpload, organizer_proof: PrivateUpload,
    ) -> ApplicationEvidenceView:
        if user.role != UserRole.STUDENT:
            raise ApplicationError(403, "Insufficient permissions.")
        with write_with_uploads(self._sessions, self._storage) as (db, keys):
            app = _load(db, application_id, user, lock=True)
            day = _day(app, day_id)
            if _day_state(day) not in {"NOT_SUBMITTED", "CORRECTION_REQUIRED"}:
                raise ApplicationError(409, "This event day is not accepting a new submission.")
            now = _utc_naive(datetime.now(timezone.utc))
            attempts = _attempts(day)
            received = max(now, attempts[-1].server_received_at + timedelta(microseconds=1)) if attempts else now
            attempt = EvidenceSubmission(
                venue_photo=store_upload(self._storage, venue_photo, user.user_id, keys),
                organizer_proof=store_upload(self._storage, organizer_proof, user.user_id, keys),
                submission_notes=data.notes or None, submitted_at=_utc_naive(data.submitted_at), server_received_at=received,
            )
            attempt.location_captures.append(LocationCapture(
                latitude=data.gps.latitude, longitude=data.gps.longitude, accuracy_meters=data.gps.accuracy_meters,
                captured_at=_utc_naive(data.gps.captured_at), server_recorded_at=now,
            ))
            day.evidence_submissions.append(attempt)
            day.day_status = EventDayStatus.PENDING
            day.verification_notes = None
            db.flush()
            _app_state(app, user)
            db.flush()
            return _view(app)

    def review(
        self, user: AuthenticatedUser, application_id: UUID, day_id: UUID, attempt_id: UUID, decision: DayEvidenceDecision,
    ) -> ApplicationEvidenceView:
        if user.role != UserRole.TUTOR:
            raise ApplicationError(403, "Insufficient permissions.")
        with self._sessions.begin() as db:
            app = _load(db, application_id, user, lock=True)
            day = _day(app, day_id)
            reopening = (
                app.status == ApplicationStatus.UNDER_TUTOR_CORRECTION_REVIEW
                and decision.review_status == EvidenceReviewStatus.CORRECTION_REQUIRED
                and _day_state(day) == "VERIFIED"
            )
            attempts = _attempts(day)
            if not any(item.id == attempt_id for item in attempts):
                raise ApplicationError(404, "Evidence submission not found.")
            current = attempts[-1]
            if current.id != attempt_id or (current.reviews and not reopening):
                raise ApplicationError(409, "This evidence has changed or already been reviewed.")
            if decision.review_status == EvidenceReviewStatus.APPROVED and not _complete(current):
                raise ApplicationError(409, "Both files and a GPS capture are required before verification.")
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            reviews = _reviews(current)
            if reviews:
                now = max(now, reviews[-1].reviewed_at + timedelta(microseconds=1))
            current.reviews.append(EvidenceReview(
                reviewed_by_tutor_id=app.assigned_tutor_id, review_status=decision.review_status,
                remarks=decision.remarks, reviewed_at=now,
            ))
            day.day_status = {
                EvidenceReviewStatus.APPROVED: EventDayStatus.VERIFIED,
                EvidenceReviewStatus.REJECTED: EventDayStatus.REJECTED,
                EvidenceReviewStatus.CORRECTION_REQUIRED: EventDayStatus.PENDING,
            }[decision.review_status]
            day.verification_notes = decision.remarks
            db.flush()
            _app_state(app, user)
            db.flush()
            return _view(app)

    def decide_hod(
        self, user: AuthenticatedUser, application_id: UUID, decision: HODDecision,
    ) -> ApplicationDetail:
        if user.role != UserRole.HOD:
            raise ApplicationError(403, "Insufficient permissions.")
        targets = {
            "APPROVE": ApplicationStatus.OD_FINALIZED,
            "REJECT": ApplicationStatus.REJECTED,
            "REQUEST_CORRECTION": ApplicationStatus.HOD_CORRECTION_REQUESTED,
        }
        with self._sessions.begin() as db:
            # Match the assignment administrator's lock order and recheck authorization in this transaction.
            db.scalar(select(User.id).where(User.id == user.user_id).with_for_update(read=True))
            app = _load(db, application_id, user, lock=True)
            assignment_id = db.scalar(_active_hod_assignment(user).where(HODAssignment.department_id == app.department_id))
            if assignment_id is None or (
                app.status != ApplicationStatus.UNDER_HOD_REVIEW
                and not any(entry.hod_assignment_id for entry in app.status_history)
            ):
                raise ApplicationError(404, "Application not found.")
            _check_revision(app, decision.expected_revision)
            if app.status != ApplicationStatus.UNDER_HOD_REVIEW or not all_days_verified(app):
                raise ApplicationError(409, "This application requires completed tutor verification and pending HOD review.")
            _transition(app, targets[decision.action], user, decision.remarks or None,
                        hod_assignment_id=assignment_id)
            db.flush()
            return _detail(_load_application(db, application_id, user))

    def download(self, user: AuthenticatedUser, application_id: UUID, attempt_id: UUID, kind: str) -> PrivateUpload:
        with self._sessions() as db:
            attempt = db.scalar(
                select(EvidenceSubmission).join(EvidenceSubmission.event_day).join(EventDay.application)
                .where(ODApplication.id == application_id, EvidenceSubmission.id == attempt_id, _scope(user))
                .options(joinedload(EvidenceSubmission.venue_photo), joinedload(EvidenceSubmission.organizer_proof))
            )
            file = (attempt.venue_photo if kind == "venue-photo" else attempt.organizer_proof) if attempt else None
            if file is None:
                raise ApplicationError(404, "Document not found.")
            return read_upload(self._storage, file)
