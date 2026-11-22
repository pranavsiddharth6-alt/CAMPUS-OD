"""Record-scoped OD submission, correction and preliminary review."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload, sessionmaker

from app.dependencies.auth import AuthenticatedUser
from app.models.academic import AcademicYear, Class, ClassTutorAssignment, HODAssignment, StudentClassEnrollment
from app.models.application import ApplicationStatusHistory, EventDay, ODApplication
from app.models.enums import AccountStatus, ApplicationStatus, DaySession, DocumentType, UserRole
from app.models.evidence import ApplicationDocument, StoredFile
from app.models.user import AuthSession, StudentProfile, TutorProfile, User
from app.schemas.application import (
    ApplicationCorrection, ApplicationDetail, ApplicationDocumentResponse, ApplicationSubmission,
    ApplicationSummary, SubmissionDay, TutorDecision,
)
from app.services.storage import LocalStorageService
from app.services.private_uploads import ApplicationError, PrivateUpload, read_upload, store_upload, write_with_uploads

_REVIEWABLE = {
    ApplicationStatus.SUBMITTED, ApplicationStatus.UNDER_TUTOR_REVIEW,
    ApplicationStatus.UNDER_TUTOR_CORRECTION_REVIEW,
}
_DECISIONS = {
    "PREAPPROVE": ApplicationStatus.PRE_APPROVED,
    "REJECT": ApplicationStatus.REJECTED,
    "REQUEST_CORRECTION": ApplicationStatus.CORRECTION_REQUESTED,
}


@dataclass(frozen=True, slots=True)
class ODFile:
    kind: DocumentType
    upload: PrivateUpload


def _history(app: ODApplication) -> list[ApplicationStatusHistory]:
    return sorted(app.status_history, key=lambda entry: (entry.created_at, entry.id))


def _transition(
    app: ODApplication, status: ApplicationStatus, user: AuthenticatedUser, remarks: str | None = None,
    *, hod_assignment_id: UUID | None = None,
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    history = _history(app)
    if history:
        now = max(now, history[-1].created_at + timedelta(microseconds=1))
    app.status_history.append(ApplicationStatusHistory(
        from_status=app.status, to_status=status, changed_by_user_id=user.user_id,
        remarks=remarks, created_at=now, hod_assignment_id=hod_assignment_id,
    ))
    app.status = status


def _update_event(db: Session, app: ODApplication, submission: ApplicationSubmission) -> None:
    app.event_name = submission.event_name
    app.event_category = submission.event_category
    app.host_institution = submission.host_institution
    app.venue_location = submission.venue_location
    app.description = submission.description
    dates = {day.event_date: day.session for day in submission.event_days}
    app.start_date, app.end_date, app.total_days = min(dates), max(dates), len(dates)
    obsolete = [day.id for day in app.event_days if day.event_date not in dates]
    if obsolete:
        # Let the FK reject dates that already have dependent records.
        try:
            db.execute(delete(EventDay).where(EventDay.application_id == app.id, EventDay.id.in_(obsolete)))
        except IntegrityError:
            raise ApplicationError(409, "An event date already has linked records and cannot be removed.") from None
        db.expire(app, ["event_days"])
    for existing in app.event_days:
        existing.session = dates.pop(existing.event_date)
        existing.is_full_day = existing.session == DaySession.FULL_DAY
    app.event_days.extend(
        EventDay(event_date=day, session=session, is_full_day=session == DaySession.FULL_DAY)
        for day, session in dates.items()
    )


def _summary(app: ODApplication) -> ApplicationSummary:
    return ApplicationSummary(
        id=app.id, application_number=app.application_number, student_name=app.student.full_name,
        student_roll_number=app.student.roll_number, tutor_name=app.assigned_tutor.full_name,
        event_name=app.event_name, event_category=app.event_category, venue_location=app.venue_location,
        start_date=app.start_date, end_date=app.end_date, total_days=app.total_days, status=app.status,
    )


def _detail(app: ODApplication) -> ApplicationDetail:
    history = _history(app)
    return ApplicationDetail(
        **_summary(app).model_dump(), host_institution=app.host_institution, description=app.description,
        event_days=[SubmissionDay(event_date=day.event_date, session=day.session)
                    for day in sorted(app.event_days, key=lambda day: day.event_date)],
        documents=[ApplicationDocumentResponse(id=doc.id, document_type=doc.document_type,
                                               filename=doc.stored_file.original_filename)
                   for doc in sorted(app.documents, key=lambda doc: (doc.uploaded_at, doc.id))],
        history=history, revision=history[-1].id if history else None,
    )


def _active_hod_assignment(user: AuthenticatedUser):
    return (
        select(HODAssignment.id)
        .join(User, User.id == HODAssignment.user_id)
        .join(AuthSession, AuthSession.user_id == User.id)
        .where(HODAssignment.user_id == user.user_id, HODAssignment.ended_at.is_(None),
               User.role == UserRole.HOD, User.account_status == AccountStatus.ACTIVE,
               AuthSession.id == user.session_id, AuthSession.revoked_at.is_(None),
               AuthSession.expires_at > datetime.now(timezone.utc).replace(tzinfo=None))
    )


def _scope(user: AuthenticatedUser, *, hod_review_only: bool = True):
    if user.role == UserRole.STUDENT:
        return ODApplication.student.has(StudentProfile.user_id == user.user_id)
    if user.role == UserRole.TUTOR:
        return ODApplication.assigned_tutor.has(TutorProfile.user_id == user.user_id)
    if user.role == UserRole.HOD:
        assignment = _active_hod_assignment(user).where(HODAssignment.department_id == ODApplication.department_id)
        if not hod_review_only:
            return assignment.exists()
        return assignment.exists() & or_(
            ODApplication.status == ApplicationStatus.UNDER_HOD_REVIEW,
            ODApplication.status_history.any(ApplicationStatusHistory.hod_assignment_id.is_not(None)),
        )
    raise ApplicationError(403, "Insufficient permissions.")


def _load(db: Session, application_id: UUID, user: AuthenticatedUser, *, lock: bool = False) -> ODApplication:
    query = select(ODApplication).where(ODApplication.id == application_id, _scope(user)).options(
        selectinload(ODApplication.student), selectinload(ODApplication.assigned_tutor),
        selectinload(ODApplication.event_days),
        selectinload(ODApplication.status_history).joinedload(ApplicationStatusHistory.hod_assignment),
        selectinload(ODApplication.documents).joinedload(ApplicationDocument.stored_file),
    )
    app = db.scalar(query.with_for_update() if lock else query)
    if app is None:
        raise ApplicationError(404, "Application not found.")
    return app


def _check_revision(app: ODApplication, expected: UUID | None) -> None:
    history = _history(app)
    if expected != (history[-1].id if history else None):
        raise ApplicationError(409, "This application changed. Reload it before trying again.")


def _resolve_assignment(db: Session, user: AuthenticatedUser) -> tuple[StudentProfile, TutorProfile]:
    student = db.scalar(
        select(StudentProfile).where(StudentProfile.user_id == user.user_id).with_for_update(read=True)
    )
    if student is None:
        raise ApplicationError(409, "A student profile and active current-year enrollment are required.")
    enrollments = db.scalars(
        select(StudentClassEnrollment)
        .join(Class, (Class.id == StudentClassEnrollment.class_id)
              & (Class.academic_year_id == StudentClassEnrollment.academic_year_id))
        .join(AcademicYear, AcademicYear.id == Class.academic_year_id)
        .where(StudentClassEnrollment.student_id == student.id, StudentClassEnrollment.is_active.is_(True),
               AcademicYear.is_current.is_(True), Class.department_id == student.department_id)
        .limit(2).with_for_update(read=True, of=(StudentClassEnrollment, Class, AcademicYear))
    ).all()
    if len(enrollments) != 1:
        raise ApplicationError(409, "Exactly one active current-year enrollment is required.")
    enrollment = enrollments[0]
    tutor = db.scalar(
        select(TutorProfile).join(ClassTutorAssignment, ClassTutorAssignment.tutor_id == TutorProfile.id)
        .join(User, User.id == TutorProfile.user_id)
        .where(ClassTutorAssignment.class_id == enrollment.class_id,
               ClassTutorAssignment.academic_year_id == enrollment.academic_year_id,
               ClassTutorAssignment.is_active.is_(True), User.role == UserRole.TUTOR,
               User.account_status == AccountStatus.ACTIVE)
        .with_for_update(read=True, of=(ClassTutorAssignment, TutorProfile, User))
    )
    if tutor is None:
        raise ApplicationError(409, "No active tutor is assigned to your class and academic year.")
    return student, tutor


class ODApplicationService:
    def __init__(self, sessions: sessionmaker[Session], storage: LocalStorageService):
        self._sessions = sessions
        self._storage = storage

    def _attach(self, app: ODApplication, files: list[ODFile], user: AuthenticatedUser, keys: list[str]) -> None:
        for item in files:
            app.documents.append(ApplicationDocument(
                document_type=item.kind, stored_file=store_upload(self._storage, item.upload, user.user_id, keys),
            ))

    def submit(self, user: AuthenticatedUser, submission: ApplicationSubmission, files: list[ODFile]) -> ApplicationDetail:
        if user.role != UserRole.STUDENT:
            raise ApplicationError(403, "Insufficient permissions.")
        if sum(item.kind == DocumentType.ORIGINAL_SIGNED_OD_FORM for item in files) != 1:
            raise ApplicationError(422, "One original signed OD form is required.")
        with write_with_uploads(self._sessions, self._storage) as (db, keys):
            student, tutor = _resolve_assignment(db, user)
            app = ODApplication(application_number=f"OD-{uuid4().hex.upper()}", student=student,
                                assigned_tutor=tutor, department_id=student.department_id)
            _update_event(db, app, submission)
            _transition(app, ApplicationStatus.SUBMITTED, user)
            self._attach(app, files, user, keys)
            db.add(app)
            db.flush()
            return _detail(app)

    def list_applications(
        self, user: AuthenticatedUser, *, view: Literal["pending", "history"] | None = None,
    ) -> list[ApplicationSummary]:
        query = select(ODApplication).where(_scope(user))
        if view == "pending":
            query = query.where(ODApplication.status == ApplicationStatus.UNDER_HOD_REVIEW)
        elif view == "history":
            query = query.where(ODApplication.status_history.any(ApplicationStatusHistory.hod_assignment_id.is_not(None)))
        with self._sessions() as db:
            apps = db.scalars(query.options(
                joinedload(ODApplication.student), joinedload(ODApplication.assigned_tutor),
            ).order_by(ODApplication.created_at.desc(), ODApplication.id)).all()
            return [_summary(app) for app in apps]

    def hod_counts(self, user: AuthenticatedUser) -> dict[str, int]:
        if user.role != UserRole.HOD:
            raise ApplicationError(403, "Insufficient permissions.")
        hod_rejected = ODApplication.status_history.any(
            ApplicationStatusHistory.hod_assignment_id.is_not(None)
            & (ApplicationStatusHistory.to_status == ApplicationStatus.REJECTED)
        )
        with self._sessions() as db:
            counts = dict(db.execute(
                select(ODApplication.status, func.count()).where(
                    _scope(user), or_(ODApplication.status != ApplicationStatus.REJECTED, hod_rejected),
                ).group_by(ODApplication.status)
            ).all())
        return {
            "pending": counts.get(ApplicationStatus.UNDER_HOD_REVIEW, 0),
            "approved": counts.get(ApplicationStatus.OD_FINALIZED, 0),
            "rejected": counts.get(ApplicationStatus.REJECTED, 0),
        }

    def detail(self, user: AuthenticatedUser, application_id: UUID) -> ApplicationDetail:
        with self._sessions() as db:
            return _detail(_load(db, application_id, user))

    def resubmit(
        self, user: AuthenticatedUser, application_id: UUID, correction: ApplicationCorrection, files: list[ODFile],
    ) -> ApplicationDetail:
        if user.role != UserRole.STUDENT:
            raise ApplicationError(403, "Insufficient permissions.")
        if any(item.kind == DocumentType.ORIGINAL_SIGNED_OD_FORM for item in files):
            raise ApplicationError(422, "The original signed OD form is kept as submitted.")
        with write_with_uploads(self._sessions, self._storage) as (db, keys):
            app = _load(db, application_id, user, lock=True)
            _check_revision(app, correction.expected_revision)
            is_hod_correction = app.status == ApplicationStatus.HOD_CORRECTION_REQUESTED
            if not is_hod_correction and app.status != ApplicationStatus.CORRECTION_REQUESTED:
                raise ApplicationError(409, "Only applications with requested corrections can be resubmitted.")
            if is_hod_correction:
                # Existing evidence is tied to this event, venue and schedule.
                fixed_fields = ("event_name", "event_category", "host_institution", "venue_location")
                if any(getattr(correction, name) != getattr(app, name) for name in fixed_fields) or (
                    {day.event_date: day.session for day in correction.event_days}
                    != {day.event_date: day.session for day in app.event_days}
                ):
                    raise ApplicationError(422, "The event and schedule are fixed after evidence verification.")
                app.description = correction.description
            else:
                _update_event(db, app, correction)
            target = ApplicationStatus.UNDER_TUTOR_CORRECTION_REVIEW if is_hod_correction else ApplicationStatus.SUBMITTED
            _transition(app, target, user, "Student resubmitted the application.")
            self._attach(app, files, user, keys)
            db.flush()
            return _detail(app)

    def decide(self, user: AuthenticatedUser, application_id: UUID, decision: TutorDecision) -> ApplicationDetail:
        if user.role != UserRole.TUTOR:
            raise ApplicationError(403, "Insufficient permissions.")
        with self._sessions.begin() as db:
            app = _load(db, application_id, user, lock=True)
            _check_revision(app, decision.expected_revision)
            if app.status not in _REVIEWABLE:
                raise ApplicationError(409, "This application is not awaiting tutor review.")
            target = _DECISIONS[decision.action]
            if app.status == ApplicationStatus.UNDER_TUTOR_CORRECTION_REVIEW:
                if decision.action == "PREAPPROVE":
                    from app.services.od_evidence import all_days_verified
                    if not all_days_verified(app):
                        raise ApplicationError(409, "Verify all required evidence before forwarding to the HOD.")
                    target = ApplicationStatus.UNDER_HOD_REVIEW
                elif decision.action == "REQUEST_CORRECTION":
                    target = ApplicationStatus.HOD_CORRECTION_REQUESTED
            _transition(app, target, user, decision.remarks)
            db.flush()
            return _detail(app)

    def download(self, user: AuthenticatedUser, application_id: UUID, document_id: UUID) -> PrivateUpload:
        with self._sessions() as db:
            row = db.scalar(
                select(StoredFile).select_from(ApplicationDocument)
                .join(ApplicationDocument.stored_file).join(ApplicationDocument.application)
                .where(ApplicationDocument.id == document_id, ODApplication.id == application_id, _scope(user))
            )
            if row is None:
                raise ApplicationError(404, "Document not found.")
            return read_upload(self._storage, row)
