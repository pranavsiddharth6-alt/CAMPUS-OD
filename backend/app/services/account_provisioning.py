"""Create pending college accounts and hand off invitations after commit."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.academic import AcademicYear, Class, Department, StudentClassEnrollment
from app.models.enums import AccountActionPurpose, AccountStatus, UserRole
from app.models.user import AccountActionToken, StudentProfile, TutorProfile, User
from app.schemas.provisioning import (
    ApprovedStudentRecord,
    ApprovedTutorRecord,
    StudentProvisioningRequest,
    TutorProvisioningRequest,
)

_IDENTITY_UNIQUE_INDEXES = {
    "ix_users_email",
    "ix_student_profiles_roll_number",
    "ix_student_profiles_register_number",
    "ix_tutor_profiles_staff_id",
}
_SQLITE_IDENTITY_CONFLICTS = {
    "UNIQUE constraint failed: users.email",
    "UNIQUE constraint failed: student_profiles.roll_number",
    "UNIQUE constraint failed: student_profiles.register_number",
    "UNIQUE constraint failed: tutor_profiles.staff_id",
}


class ProvisioningValidationError(ValueError):
    """Identity or academic information could not be verified."""


class ProvisioningConflictError(Exception):
    def __init__(self):
        super().__init__("An account with those details already exists.")


class ProvisioningStoreError(RuntimeError):
    def __init__(self):
        super().__init__("Account provisioning could not be saved.")


@dataclass(frozen=True, slots=True)
class ProvisionedAccount:
    user_id: UUID
    profile_id: UUID
    invitation_id: UUID


@dataclass(frozen=True, slots=True)
class ActivationInvitation:
    invitation_id: UUID
    expires_at: datetime
    recipient: str = field(repr=False)
    token: SecretStr = field(repr=False)


# A delivery adapter returns True only after accepting the invitation, or raises on failure.
InvitationDelivery = Callable[[ActivationInvitation], bool]


class InvitationDeliveryError(RuntimeError):
    """Provisioning committed but the delivery adapter did not acknowledge the invitation."""

    def __init__(self, account: ProvisionedAccount, invitation: ActivationInvitation):
        super().__init__("Account created, but invitation delivery was not confirmed.")
        self.account = account
        # Available for an authorized in-process retry. Treat this as a secret-bearing handoff.
        self.invitation = invitation


def _is_identity_conflict(error: IntegrityError) -> bool:
    details = error.orig.args[0] if error.orig.args else None
    if isinstance(details, dict):  # pg8000 PostgreSQL error fields
        return details.get("C") == "23505" and details.get("n") in _IDENTITY_UNIQUE_INDEXES
    # The isolated SQLite fixtures use the same uniqueness rules.
    return getattr(error.orig, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_UNIQUE" and (
        details in _SQLITE_IDENTITY_CONFLICTS
    )


class AccountProvisioningService:
    """Internal service. Callers supply approved records independently of the request.

    A future HTTP caller must enforce ADMIN authorization before calling this service.
    """

    def __init__(self, *, session_factory: sessionmaker[Session], deliver_invitation: InvitationDelivery):
        if not callable(deliver_invitation):
            raise ValueError("An invitation delivery adapter is required.")
        self._sessions = session_factory
        self._deliver_invitation = deliver_invitation
        self._invitation_lifetime = timedelta(hours=settings.AUTH_INVITATION_LIFETIME_HOURS)

    @contextmanager
    def _transaction(self) -> Iterator[Session]:
        try:
            with self._sessions.begin() as db:
                yield db
        except IntegrityError as error:
            # The unique indexes arbitrate both ordinary duplicates and concurrent attempts.
            if _is_identity_conflict(error):
                raise ProvisioningConflictError() from None
            raise ProvisioningStoreError() from None
        except SQLAlchemyError:
            raise ProvisioningStoreError() from None

    def provision_student(
        self, request: StudentProvisioningRequest, *, approved: ApprovedStudentRecord,
    ) -> ProvisionedAccount:
        if not isinstance(approved, ApprovedStudentRecord) or (
            request.model_dump() != approved.model_dump(exclude={"academic_year_id"})
        ):
            raise ProvisioningValidationError("Student details do not match the approved roster.")

        with self._transaction() as db:
            academic_year_id = db.scalar(
                select(Class.academic_year_id)
                .join(AcademicYear, AcademicYear.id == Class.academic_year_id)
                .join(Department, Department.id == Class.department_id)
                .where(Class.id == request.class_id, Class.department_id == request.department_id,
                       AcademicYear.id == approved.academic_year_id)
                .with_for_update(read=True, of=Class)
            )
            if academic_year_id is None:
                raise ProvisioningValidationError("The student's approved class, department and year do not match.")

            profile = StudentProfile(
                full_name=request.full_name, department_id=request.department_id,
                roll_number=request.roll_number, register_number=request.register_number,
            )
            profile.enrollments.append(StudentClassEnrollment(
                class_id=request.class_id, academic_year_id=academic_year_id, is_active=True,
            ))
            user = User(email=request.email, role=UserRole.STUDENT, student_profile=profile,
                        account_status=AccountStatus.PENDING_ACTIVATION, auth_version=0)
            account, invitation = self._stage_invitation(db, user, profile)

        self._handoff(account, invitation)
        return account

    def provision_tutor(
        self, request: TutorProvisioningRequest, *, approved: ApprovedTutorRecord,
    ) -> ProvisionedAccount:
        if not isinstance(approved, ApprovedTutorRecord) or request.model_dump() != approved.model_dump():
            raise ProvisioningValidationError("Tutor details do not match the approved staff record.")

        with self._transaction() as db:
            department_id = db.scalar(
                select(Department.id).where(Department.id == request.department_id).with_for_update(read=True)
            )
            if department_id is None:
                raise ProvisioningValidationError("The tutor's approved department does not exist.")

            profile = TutorProfile(
                full_name=request.full_name, department_id=department_id,
                staff_id=request.staff_id, designation=request.designation,
            )
            user = User(email=request.email, role=UserRole.TUTOR, tutor_profile=profile,
                        account_status=AccountStatus.PENDING_ACTIVATION, auth_version=0)
            account, invitation = self._stage_invitation(db, user, profile)

        self._handoff(account, invitation)
        return account

    def _stage_invitation(
        self, db: Session, user: User, profile: StudentProfile | TutorProfile,
    ) -> tuple[ProvisionedAccount, ActivationInvitation]:
        now = datetime.now(timezone.utc)
        token = token_urlsafe(32)
        record = AccountActionToken(
            user=user, purpose=AccountActionPurpose.ACTIVATION, auth_version=user.auth_version,
            token_digest=sha256(token.encode("ascii")).digest(), created_at=now,
            expires_at=now + self._invitation_lifetime,
        )
        db.add_all([user, record])
        db.flush()
        return (
            ProvisionedAccount(user.id, profile.id, record.id),
            ActivationInvitation(record.id, record.expires_at, user.email, SecretStr(token)),
        )

    def _handoff(self, account: ProvisionedAccount, invitation: ActivationInvitation) -> None:
        try:
            accepted = self._deliver_invitation(invitation)
        except Exception:
            # Adapter errors may contain the raw token, so omit them from the exception chain.
            accepted = False
        if accepted is not True:
            raise InvitationDeliveryError(account, invitation)
