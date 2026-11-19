import traceback
import unittest
from datetime import date, timedelta, timezone
from hashlib import sha256
from unittest.mock import Mock, patch
from uuid import uuid4

import sqlalchemy as sa
from pg8000.dbapi import DatabaseError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.models.academic import AcademicYear, Class, ClassTutorAssignment, Department, StudentClassEnrollment
from app.models.enums import AccountActionPurpose, AccountStatus, UserRole
from app.models.user import AccountActionToken, StudentProfile, TutorProfile, User
from app.schemas.auth import LoginRequest
from app.schemas.provisioning import (
    ApprovedStudentRecord,
    ApprovedTutorRecord,
    StudentProvisioningRequest,
    TutorProvisioningRequest,
)
from app.services import account_provisioning
from app.services.account_provisioning import (
    AccountProvisioningService,
    InvitationDeliveryError,
    ProvisioningConflictError,
    ProvisioningStoreError,
    ProvisioningValidationError,
)


class AccountProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch(
            "pg8000.dbapi.connect", side_effect=AssertionError("Provisioning tests cannot connect to PostgreSQL"),
        ))
        self.enterContext(patch.object(account_provisioning.settings, "AUTH_INVITATION_LIFETIME_HOURS", 24))
        engine = sa.create_engine("sqlite://", hide_parameters=True)
        self.addCleanup(engine.dispose)
        with engine.begin() as db:
            db.exec_driver_sql("PRAGMA foreign_keys = ON")
            User.metadata.create_all(db, tables=[model.__table__ for model in (
                User, StudentProfile, TutorProfile, Department, AcademicYear, Class,
                StudentClassEnrollment, ClassTutorAssignment, AccountActionToken,
            )])
        self.factory = sessionmaker(bind=engine)
        self.delivery = Mock(return_value=True)
        self.service = AccountProvisioningService(session_factory=self.factory, deliver_invitation=self.delivery)

        self.department_id, self.other_department_id, self.class_id = uuid4(), uuid4(), uuid4()
        self.year_id, self.other_year_id = uuid4(), uuid4()
        with self.factory.begin() as db:
            db.add_all([
                Department(id=self.department_id, code="DEMO", name="Demo Department"),
                Department(id=self.other_department_id, code="OTHER", name="Other Demo Department"),
                AcademicYear(id=self.year_id, name="Demo year", start_date=date(2026, 6, 1),
                             end_date=date(2027, 5, 31), is_current=False),
                AcademicYear(id=self.other_year_id, name="Other demo year", start_date=date(2027, 6, 1),
                             end_date=date(2028, 5, 31), is_current=True),
                Class(id=self.class_id, name="Demo Class", department_id=self.department_id,
                      academic_year_id=self.year_id, batch="Demo", semester=1),
            ])

    def student(self, **changes):
        return StudentProvisioningRequest.model_validate({
            "email": "  Demo.Student@EXAMPLE.COM  ", "full_name": "Demo Student", "roll_number": "DEMO-R1",
            "register_number": "DEMO-G1", "department_id": self.department_id, "class_id": self.class_id,
        } | changes)

    def tutor(self, **changes):
        return TutorProvisioningRequest.model_validate({
            "email": "Demo.Tutor@example.com", "full_name": "Demo Tutor", "staff_id": "DEMO-S1",
            "designation": "Demo Lecturer", "department_id": self.department_id,
        } | changes)

    def roster(self, request, *, academic_year_id=None):
        return ApprovedStudentRecord(**request.model_dump(), academic_year_id=academic_year_id or self.year_id)

    def staff(self, request):
        return ApprovedTutorRecord(**request.model_dump())

    def assert_counts(self, users=0, students=0, tutors=0, enrollments=0, tokens=0):
        with self.factory() as db:
            for model, expected in zip(
                (User, StudentProfile, TutorProfile, StudentClassEnrollment, AccountActionToken),
                (users, students, tutors, enrollments, tokens),
                strict=True,
            ):
                self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(model)), expected)
            self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(ClassTutorAssignment)), 0)

    def test_student_provisioning_commits_profile_enrollment_and_invitation_before_handoff(self):
        request = self.student()
        committed = Mock()
        sa.event.listen(self.factory, "after_commit", committed)
        self.addCleanup(sa.event.remove, self.factory, "after_commit", committed)

        def receive(invitation):
            committed.assert_called_once()
            self.assert_counts(users=1, students=1, enrollments=1, tokens=1)
            with self.factory() as db:
                record = db.get(AccountActionToken, invitation.invitation_id)
                self.assertTrue(record.token_digest == sha256(invitation.token.get_secret_value().encode("ascii")).digest())
            return True

        self.delivery.side_effect = receive
        result = self.service.provision_student(request, approved=self.roster(request))
        self.delivery.assert_called_once()
        invitation = self.delivery.call_args.args[0]
        self.assertEqual(result.invitation_id, invitation.invitation_id)
        self.assertEqual(invitation.recipient, LoginRequest(
            email="  Demo.Student@EXAMPLE.COM  ", password="synthetic fixture value",
        ).email)

        with self.factory() as db:
            user = db.get(User, result.user_id)
            self.assertEqual((user.role, user.account_status, user.auth_version),
                             (UserRole.STUDENT, AccountStatus.PENDING_ACTIVATION, 0))
            self.assertFalse(user.is_active)
            self.assertIsNone(user.hashed_password)
            profile = user.student_profile
            self.assertEqual((profile.id, profile.department_id, profile.roll_number, profile.register_number),
                             (result.profile_id, self.department_id, request.roll_number, request.register_number))
            enrollment, = profile.enrollments
            self.assertEqual((enrollment.class_id, enrollment.academic_year_id, enrollment.is_active),
                             (self.class_id, self.year_id, True))
            record = db.get(AccountActionToken, result.invitation_id)
            self.assertEqual((record.user_id, record.purpose, record.auth_version),
                             (user.id, AccountActionPurpose.ACTIVATION, user.auth_version))
            self.assertEqual(record.expires_at - record.created_at, timedelta(hours=24))
            self.assertEqual(invitation.expires_at, record.expires_at.replace(tzinfo=timezone.utc))
            self.assertIsNone(record.consumed_at)
            self.assertIsNone(record.invalidated_at)
            self.assertFalse(record.token_digest == invitation.token.get_secret_value().encode("ascii"))

        secret = invitation.token.get_secret_value()
        self.assertEqual(len(secret), 43)
        self.assertFalse(any(secret in rendered for rendered in (repr(result), repr(invitation), str(invitation.token))))

    def test_tutor_provisioning_is_pending_and_does_not_require_class_assignment(self):
        request = self.tutor()
        with patch.object(account_provisioning.settings, "AUTH_INVITATION_LIFETIME_HOURS", 3):
            service = AccountProvisioningService(session_factory=self.factory, deliver_invitation=self.delivery)
        result = service.provision_tutor(request, approved=self.staff(request))
        self.assert_counts(users=1, tutors=1, tokens=1)
        self.delivery.assert_called_once()
        with self.factory() as db:
            user = db.get(User, result.user_id)
            self.assertEqual((user.role, user.account_status), (UserRole.TUTOR, AccountStatus.PENDING_ACTIVATION))
            self.assertFalse(user.is_active)
            self.assertIsNone(user.hashed_password)
            profile = user.tutor_profile
            self.assertEqual((profile.id, profile.staff_id, profile.designation, profile.department_id),
                             (result.profile_id, request.staff_id, request.designation, self.department_id))
            record = db.get(AccountActionToken, result.invitation_id)
            self.assertEqual(record.expires_at - record.created_at, timedelta(hours=3))

    def test_student_rejects_missing_class_and_department_or_year_mismatch(self):
        for request, year in (
            (self.student(class_id=uuid4()), self.year_id),
            (self.student(department_id=self.other_department_id), self.year_id),
            (self.student(), self.other_year_id),
        ):
            with self.assertRaises(ProvisioningValidationError):
                self.service.provision_student(request, approved=self.roster(request, academic_year_id=year))
        self.assert_counts()
        self.delivery.assert_not_called()

    def test_tutor_rejects_nonexistent_department(self):
        request = self.tutor(department_id=uuid4())
        with self.assertRaises(ProvisioningValidationError):
            self.service.provision_tutor(request, approved=self.staff(request))
        self.assert_counts()
        self.delivery.assert_not_called()

    def test_student_details_must_match_an_approved_record(self):
        approved = self.roster(self.student())
        for overrides in (
            {"email": "other@example.com"}, {"full_name": "Other Student"}, {"roll_number": "OTHER-R"},
            {"register_number": "OTHER-G"}, {"department_id": uuid4()}, {"class_id": uuid4()},
        ):
            with self.assertRaises(ProvisioningValidationError):
                self.service.provision_student(self.student(**overrides), approved=approved)
        self.assert_counts()
        self.delivery.assert_not_called()

    def test_tutor_details_must_match_an_approved_record(self):
        approved = self.staff(self.tutor())
        for overrides in (
            {"email": "other@example.com"}, {"full_name": "Other Tutor"}, {"staff_id": "OTHER-S"},
            {"designation": "Other Title"}, {"department_id": uuid4()},
        ):
            with self.assertRaises(ProvisioningValidationError):
                self.service.provision_tutor(self.tutor(**overrides), approved=approved)
        with self.assertRaises(ProvisioningValidationError):
            self.service.provision_tutor(self.tutor(), approved=self.tutor())
        self.assert_counts()
        self.delivery.assert_not_called()

    def test_requests_reject_unknown_and_forbidden_fields_without_rendering_values(self):
        marker = "synthetic credential that must never appear"
        for request in (self.student(), self.tutor()):
            for name in ("role", "password", "hashed_password", "password_hash", "account_status",
                         "is_active", "auth_version", "academic_year_id", "unexpected"):
                with self.subTest(schema=type(request).__name__, field=name):
                    with self.assertRaises(ValidationError) as raised:
                        type(request).model_validate(request.model_dump() | {name: marker})
                    self.assertFalse(marker in str(raised.exception))
                    self.assertEqual(raised.exception.errors(include_input=False)[0]["type"], "extra_forbidden")

    def test_duplicate_student_roll_register_and_email_do_not_leave_partial_rows(self):
        initial = self.student()
        self.service.provision_student(initial, approved=self.roster(initial))
        for request in (
            self.student(email="Demo.Student@example.com", roll_number="DEMO-R2", register_number="DEMO-G2"),
            self.student(email="another@example.com", register_number="DEMO-G2"),
            self.student(email="another@example.com", roll_number="DEMO-R2"),
        ):
            with self.assertRaisesRegex(ProvisioningConflictError, "^An account with those details already exists"):
                self.service.provision_student(request, approved=self.roster(request))
        self.assert_counts(users=1, students=1, enrollments=1, tokens=1)
        self.delivery.assert_called_once()

    def test_duplicate_tutor_staff_id_and_cross_role_email_are_rejected(self):
        tutor = self.tutor()
        self.service.provision_tutor(tutor, approved=self.staff(tutor))
        duplicate = self.tutor(email="other@example.com")
        with self.assertRaises(ProvisioningConflictError):
            self.service.provision_tutor(duplicate, approved=self.staff(duplicate))
        student = self.student(email=tutor.email)
        with self.assertRaises(ProvisioningConflictError):
            self.service.provision_student(student, approved=self.roster(student))
        self.assert_counts(users=1, tutors=1, tokens=1)
        self.delivery.assert_called_once()

    def test_postgresql_concurrent_identity_conflict_is_sanitized_and_rolled_back(self):
        marker = "synthetic private driver details"

        def conflict(db):
            raise IntegrityError("synthetic statement", None, DatabaseError({
                "C": "23505", "n": "ix_users_email", "D": marker,
            }))

        sa.event.listen(self.factory, "before_commit", conflict)
        self.addCleanup(sa.event.remove, self.factory, "before_commit", conflict)
        request = self.student()
        with self.assertRaises(ProvisioningConflictError) as raised:
            self.service.provision_student(request, approved=self.roster(request))
        self.assertFalse(marker in "".join(traceback.format_exception(raised.exception)))
        self.assert_counts()
        self.delivery.assert_not_called()

    def test_commit_failure_rolls_back_all_rows_and_skips_delivery(self):
        marker = "synthetic private SQL error"

        def fail(db):
            raise SQLAlchemyError(marker)

        sa.event.listen(self.factory, "before_commit", fail)
        self.addCleanup(sa.event.remove, self.factory, "before_commit", fail)
        request = self.student()
        with self.assertRaises(ProvisioningStoreError) as raised:
            self.service.provision_student(request, approved=self.roster(request))
        self.assertFalse(marker in "".join(traceback.format_exception(raised.exception)))
        self.assert_counts()
        self.delivery.assert_not_called()

    def test_delivery_exception_reports_committed_account_and_retains_redacted_handoff(self):
        def fail(invitation):
            raise RuntimeError(invitation.token.get_secret_value())

        self.delivery.side_effect = fail
        request = self.tutor()
        with self.assertRaises(InvitationDeliveryError) as raised:
            self.service.provision_tutor(request, approved=self.staff(request))
        error = raised.exception
        self.assertIs(error.invitation, self.delivery.call_args.args[0])
        self.assertEqual(error.account.invitation_id, error.invitation.invitation_id)
        self.assertIsNone(error.__context__)
        self.assertFalse(error.invitation.token.get_secret_value() in "".join(traceback.format_exception(error)))
        self.assert_counts(users=1, tutors=1, tokens=1)

    def test_delivery_requires_positive_acknowledgement(self):
        self.delivery.return_value = False
        request = self.tutor()
        with self.assertRaises(InvitationDeliveryError):
            self.service.provision_tutor(request, approved=self.staff(request))
        self.assert_counts(users=1, tutors=1, tokens=1)
