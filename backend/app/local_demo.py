"""Explicit operator commands for an isolated fictional Campus OD demo."""

import argparse
import getpass
import os
import secrets
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.passwords import hash_new_password
from app.database.demo import create_demo_engine, upgrade_demo_admin, upgrade_demo_hod, upgrade_demo_map_od
from app.database.session import Base
from app.models import (
    AcademicYear, AccountActionToken, AdminProfile, AuthSession, Class, Department, RefreshToken,
    StudentClassEnrollment, StudentProfile, TutorProfile, User, UserRole,
    ApplicationDocument, ApplicationStatusHistory, ClassTutorAssignment, EventDay, ODApplication, StoredFile,
    EvidenceReview, EvidenceSubmission, LocationCapture,
)
from app.models.academic import HODAssignment
from app.models.enums import AccountStatus
from app.services.demo_accounts import (
    DEMO_ADMIN_EMAIL, DEMO_ORIGIN, DEMO_STUDENT, DEMO_TUTOR, DemoInvitationOutbox, seed_demo_academics,
)

_OD_MODELS = (
    ClassTutorAssignment, HODAssignment, ODApplication, EventDay, StoredFile, ApplicationDocument, ApplicationStatusHistory,
    EvidenceSubmission, LocationCapture, EvidenceReview,
)


def _write_private(path: Path, data: bytes) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as file:
        file.write(data)


def initialize_demo(directory: Path) -> None:
    from cryptography.fernet import Fernet

    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    (directory / "invitations").mkdir(mode=0o700)
    _write_private(directory / "invitation.key", Fernet.generate_key())
    _write_private(directory / "jwt.key", secrets.token_urlsafe(48).encode("ascii"))
    _write_private(directory / "campus_od.sqlite3", b"")
    engine = create_demo_engine(directory)
    try:
        with engine.begin() as db:
            Base.metadata.create_all(db, tables=[model.__table__ for model in (
                User, AdminProfile, StudentProfile, TutorProfile, Department, AcademicYear, Class,
                StudentClassEnrollment, AuthSession, RefreshToken, AccountActionToken, *_OD_MODELS,
            )])
        upgrade_demo_hod(engine)
        upgrade_demo_admin(engine)
        upgrade_demo_map_od(engine)
        with sessionmaker(engine).begin() as db:
            seed_demo_academics(db)
    finally:
        engine.dispose()
    _write_private(directory / "initialized", b"Campus OD local demo\n")


def _require_demo(directory: Path) -> None:
    if not all((directory / name).is_file() for name in ("initialized", "campus_od.sqlite3", "jwt.key", "invitation.key")):
        raise ValueError("Initialize a local demo directory first.")


def bootstrap_demo_admin(directory: Path, password: str) -> None:
    _require_demo(directory)
    password_hash = hash_new_password(password)
    engine = create_demo_engine(directory)
    try:
        upgrade_demo_admin(engine)
        with sessionmaker(engine).begin() as db:
            if db.scalar(select(User.id).where(User.role == UserRole.ADMIN).limit(1)) is not None:
                raise ValueError("A local demo administrator already exists.")
            db.add(User(
                email=DEMO_ADMIN_EMAIL, role=UserRole.ADMIN, account_status=AccountStatus.ACTIVE,
                hashed_password=password_hash,
                admin_profile=AdminProfile(staff_id="DEMO-ADMIN-001", full_name="Demo Administrator",
                                           designation="Demo Operator"),
            ))
    finally:
        engine.dispose()


def prepare_demo_od(directory: Path) -> None:
    _require_demo(directory)
    engine = create_demo_engine(directory)
    try:
        with engine.begin() as connection:
            Base.metadata.create_all(connection, tables=[model.__table__ for model in _OD_MODELS])
        upgrade_demo_hod(engine)
        upgrade_demo_admin(engine)
        upgrade_demo_map_od(engine)
        with sessionmaker(engine).begin() as db:
            tutor_id = db.scalar(select(TutorProfile.id).join(TutorProfile.user).where(
                User.email == DEMO_TUTOR.email, User.role == UserRole.TUTOR, User.account_status == AccountStatus.ACTIVE,
            ))
            if tutor_id is None:
                raise ValueError("Provision and activate the fictional demo tutor first.")
            assignment = db.scalar(select(ClassTutorAssignment).where(
                ClassTutorAssignment.class_id == DEMO_STUDENT.class_id,
                ClassTutorAssignment.academic_year_id == DEMO_STUDENT.academic_year_id,
            ))
            if assignment is None:
                db.add(ClassTutorAssignment(
                    tutor_id=tutor_id, class_id=DEMO_STUDENT.class_id,
                    academic_year_id=DEMO_STUDENT.academic_year_id, is_active=True,
                ))
            elif assignment.tutor_id != tutor_id or not assignment.is_active:
                raise ValueError("The demo class already has a different or inactive tutor assignment.")
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path.home() / ".campus-od-demo")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    bootstrap = commands.add_parser("bootstrap-admin")
    bootstrap.add_argument("--confirm-demo-admin", action="store_true", required=True)
    commands.add_parser("serve")
    commands.add_parser("prepare-od")
    copy = commands.add_parser("copy-invitation")
    copy.add_argument("invitation_id", type=UUID)
    args = parser.parse_args()
    directory = args.directory.expanduser().resolve()
    try:
        if args.command == "init":
            initialize_demo(directory)
            print("Local demo initialized.")
            return 0
        _require_demo(directory)
        if args.command == "bootstrap-admin":
            if not sys.stdin.isatty():
                raise ValueError("Use an interactive local terminal to set the demo administrator password.")
            password = getpass.getpass("Demo administrator password: ")
            if password != getpass.getpass("Confirm demo administrator password: "):
                raise ValueError("Passwords did not match.")
            bootstrap_demo_admin(directory, password)
            print(f"Created the local demo administrator {DEMO_ADMIN_EMAIL}.")
        elif args.command == "prepare-od":
            prepare_demo_od(directory)
            print("Local OD workflow is ready.")
        elif args.command == "copy-invitation":
            token = DemoInvitationOutbox(directory).read_unexpired(args.invitation_id)
            subprocess.run(["clip.exe"], input=token.encode("ascii"), check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("Invitation copied to the local clipboard.")
        else:
            import uvicorn

            settings.ENVIRONMENT = "local-demo"
            settings.DEBUG = False
            settings.LOCAL_DEMO_DIR = directory
            settings.STORAGE_DIR = str(directory / "storage")
            settings.CORS_ORIGINS = [DEMO_ORIGIN]
            settings.JWT_SIGNING_SECRET = SecretStr((directory / "jwt.key").read_text(encoding="ascii"))
            settings.JWT_ISSUER = "campus-od-local-demo"
            settings.JWT_AUDIENCE = "campus-od-local-demo-browser"
            settings.JWT_ALGORITHM = "HS256"
            settings.JWT_ACCESS_TOKEN_MINUTES = 10
            uvicorn.run("app.main:app", host="127.0.0.1", port=8001)
    except (ValueError, OSError, subprocess.CalledProcessError, EOFError) as error:
        # Display controlled validation messages only.
        print(str(error) if type(error) is ValueError else "Local demo operation failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
