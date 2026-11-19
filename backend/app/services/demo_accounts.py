"""Fictional roster and encrypted invitation handoff for the local operator."""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.academic import AcademicYear, Class, Department
from app.schemas.provisioning import ApprovedStudentRecord, ApprovedTutorRecord
from app.services.account_provisioning import ActivationInvitation

DEMO_ORIGIN = "http://localhost:5173"
DEMO_ADMIN_EMAIL = "demo.admin@example.com"
_DEPARTMENT = UUID("dc100000-0000-4000-8000-000000000001")
_YEAR = UUID("dc100000-0000-4000-8000-000000000002")
_CLASS = UUID("dc100000-0000-4000-8000-000000000003")

DEMO_STUDENT = ApprovedStudentRecord(
    email="demo.student@example.com", full_name="Demo Student", roll_number="DEMO-R001",
    register_number="DEMO-G001", department_id=_DEPARTMENT, class_id=_CLASS, academic_year_id=_YEAR,
)
DEMO_TUTOR = ApprovedTutorRecord(
    email="demo.tutor@example.com", full_name="Demo Tutor", staff_id="DEMO-T001",
    designation="Demo Lecturer", department_id=_DEPARTMENT,
)


def seed_demo_academics(db: Session) -> None:
    db.add_all([
        Department(id=_DEPARTMENT, code="DEMO", name="Demo Department"),
        AcademicYear(id=_YEAR, name="Demo Academic Year", start_date=date(2026, 6, 1),
                     end_date=date(2027, 5, 31), is_current=True),
        Class(id=_CLASS, name="Demo Class", department_id=_DEPARTMENT, academic_year_id=_YEAR,
              batch="Demo", semester=1),
    ])


class DemoInvitationOutbox:
    def __init__(self, directory: Path):
        from cryptography.fernet import Fernet

        self.directory = directory / "invitations"
        self._cipher = Fernet((directory / "invitation.key").read_bytes())

    def __call__(self, invitation: ActivationInvitation) -> bool:
        payload = json.dumps({
            "expires": invitation.expires_at.isoformat(),
            "token": invitation.token.get_secret_value(),
        }).encode("utf-8")
        encrypted = self._cipher.encrypt(payload)
        temporary = None
        try:
            with NamedTemporaryFile(dir=self.directory, delete=False) as file:
                temporary = Path(file.name)
                file.write(encrypted)
            os.replace(temporary, self.directory / f"{invitation.invitation_id}.invite")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return True

    def read_unexpired(self, invitation_id: UUID) -> str:
        from cryptography.fernet import InvalidToken

        try:
            payload = json.loads(self._cipher.decrypt((self.directory / f"{invitation_id}.invite").read_bytes()))
        except (FileNotFoundError, InvalidToken, ValueError):
            raise ValueError("No readable local invitation was found.") from None
        if datetime.fromisoformat(payload["expires"]) <= datetime.now(timezone.utc):
            raise ValueError("This local invitation has expired.")
        return payload["token"]
