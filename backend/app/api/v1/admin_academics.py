"""Read demo academic records and manage class-tutor mappings on localhost."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload
from starlette.concurrency import run_in_threadpool

from app.api.v1.admin_provisioning import local_demo_directory
from app.api.v1.auth import _COOKIE_AUTH_GUARDS, _NO_STORE, read_auth_json
from app.database.session import get_session_factory
from app.dependencies.auth import AuthenticatedUser, require_roles
from app.models.academic import Class, ClassTutorAssignment, Department, HODAssignment, StudentClassEnrollment
from app.models.enums import AccountStatus, UserRole
from app.models.admin_audit import record_admin_change
from app.models.user import AuthSession, TutorProfile, User
from app.services.auth_sessions import AuthSessionService

router = APIRouter(
    prefix="/admin/academics", tags=["Local demo administration"],
    dependencies=[Depends(require_roles(UserRole.ADMIN)), Depends(local_demo_directory)],
)


class TutorMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tutor_id: UUID | None


Admin = Annotated[AuthenticatedUser, Depends(require_roles(UserRole.ADMIN))]


@router.get("")
def academics(response: Response):
    response.headers.update(_NO_STORE)
    try:
        sessions = get_session_factory()
        with sessions() as db:
            classes = db.scalars(select(Class).options(
                joinedload(Class.department), joinedload(Class.academic_year),
                selectinload(Class.enrollments).joinedload(StudentClassEnrollment.student),
                selectinload(Class.tutor_assignments).joinedload(ClassTutorAssignment.tutor),
            ).order_by(Class.name, Class.id)).all()
            tutors = db.scalars(select(TutorProfile).join(TutorProfile.user).where(
                User.role == UserRole.TUTOR, User.account_status == AccountStatus.ACTIVE,
            ).order_by(TutorProfile.full_name, TutorProfile.id)).all()
            records = []
            for item in classes:
                mapping = next(iter(item.tutor_assignments), None)
                records.append({
                    "id": item.id, "name": item.name, "department": item.department.name,
                    "academic_year": item.academic_year.name, "current_year": item.academic_year.is_current,
                    "students": [{"name": enrollment.student.full_name, "roll_number": enrollment.student.roll_number}
                                 for enrollment in item.enrollments if enrollment.is_active],
                    "assignment": {"tutor_id": mapping.tutor_id, "tutor_name": mapping.tutor.full_name,
                                   "active": mapping.is_active} if mapping else None,
                    "available_tutors": [{"id": tutor.id, "name": tutor.full_name}
                                         for tutor in tutors if tutor.department_id == item.department_id],
                })
            return {"classes": records}
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        raise HTTPException(503, "Academic records are temporarily unavailable.", headers=_NO_STORE) from None


def _set_mapping(class_id: UUID, payload: TutorMapping, actor_id: UUID) -> None:
    try:
        with get_session_factory().begin() as db:
            item = db.scalar(select(Class).where(Class.id == class_id).with_for_update())
            if item is None:
                raise HTTPException(404, "Class not found.", headers=_NO_STORE)
            existing = db.scalar(select(ClassTutorAssignment).where(
                ClassTutorAssignment.class_id == item.id, ClassTutorAssignment.academic_year_id == item.academic_year_id,
            ).with_for_update())
            previous = existing.tutor_id if existing and existing.is_active else None
            if previous == payload.tutor_id:
                return
            record_admin_change(db, actor_id, "tutor_assignment", class_id, "update",
                                previous_tutor_id=str(previous) if previous else None,
                                tutor_id=str(payload.tutor_id) if payload.tutor_id else None)
            if payload.tutor_id is None:
                if existing is not None:
                    existing.is_active = False
                return
            if not item.is_active or not item.department.is_active:
                raise HTTPException(409, "Choose an active class and department.", headers=_NO_STORE)
            tutor = db.scalar(select(TutorProfile.id).join(TutorProfile.user).where(
                TutorProfile.id == payload.tutor_id, TutorProfile.department_id == item.department_id,
                User.role == UserRole.TUTOR, User.account_status == AccountStatus.ACTIVE,
            ).with_for_update(read=True, of=(TutorProfile, User)))
            if tutor is None:
                raise HTTPException(409, "Choose an active tutor in this classâ€™s department.", headers=_NO_STORE)
            if existing is None:
                db.add(ClassTutorAssignment(class_id=item.id, academic_year_id=item.academic_year_id,
                                            tutor_id=tutor, is_active=True))
            elif existing.tutor_id != tutor or not existing.is_active:
                existing.tutor_id = tutor
                existing.is_active = True
                existing.assigned_at = datetime.now(timezone.utc).replace(tzinfo=None)
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        raise HTTPException(503, "The class assignment could not be saved.", headers=_NO_STORE) from None


@router.put("/classes/{class_id}/tutor", status_code=204, dependencies=_COOKIE_AUTH_GUARDS)
async def set_mapping(class_id: UUID, request: Request, admin: Admin) -> Response:
    payload = await read_auth_json(request, TutorMapping)
    if payload is None:
        raise HTTPException(422, "Choose a tutor or explicitly clear the mapping.", headers=_NO_STORE)
    await run_in_threadpool(_set_mapping, class_id, payload, admin.user_id)
    return Response(status_code=204, headers=_NO_STORE)


class HODMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None
    expected_assignment_id: UUID | None


@router.get("/hod-assignments")
def hod_assignments(response: Response):
    response.headers.update(_NO_STORE)
    try:
        with get_session_factory()() as db:
            departments = db.scalars(select(Department).order_by(Department.name)).all()
            rows = db.execute(select(HODAssignment, User.email, User.role, User.account_status, User.hod_display_name)
                              .join(User, User.id == HODAssignment.user_id)
                              .order_by(HODAssignment.assigned_at.desc(), HODAssignment.id)).all()
            history = {department.id: [] for department in departments}
            available = {}
            assigned_users = set()
            for mapping, email, role, status, display_name in rows:
                history[mapping.department_id].append({
                    "id": mapping.id, "user_id": mapping.user_id, "name": mapping.full_name,
                    "email": email, "account_status": status, "assigned_at": mapping.assigned_at,
                    "ended_at": mapping.ended_at,
                })
                if mapping.ended_at is None:
                    assigned_users.add(mapping.user_id)
                if role == UserRole.HOD and status == AccountStatus.ACTIVE:
                    available.setdefault(mapping.user_id, {"id": mapping.user_id, "name": display_name or mapping.full_name})
            return {
                "departments": [{"id": item.id, "name": item.name, "history": history[item.id]}
                                for item in departments],
                "available_hods": [entry for user_id, entry in available.items() if user_id not in assigned_users],
            }
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        raise HTTPException(503, "HOD assignments are temporarily unavailable.", headers=_NO_STORE) from None


def _set_hod_mapping(department_id: UUID, payload: HODMapping, actor_id: UUID) -> None:
    try:
        with get_session_factory().begin() as db:
            department = db.get(Department, department_id, with_for_update=True)
            if department is None:
                raise HTTPException(404, "Department not found.", headers=_NO_STORE)
            current = db.scalar(select(HODAssignment).where(
                HODAssignment.department_id == department_id, HODAssignment.ended_at.is_(None),
            ))
            if payload.expected_assignment_id != (current.id if current else None):
                raise HTTPException(409, "The assignment changed. Refresh and try again.", headers=_NO_STORE)
            if payload.user_id == (current.user_id if current else None):
                return
            affected = {user_id for user_id in (payload.user_id, current.user_id if current else None) if user_id}
            users = {user.id: user for user in db.scalars(
                select(User).where(User.id.in_(affected)).order_by(User.id).with_for_update()
            )}
            name = None
            if payload.user_id:
                if not department.is_active:
                    raise HTTPException(409, "Choose an active department.", headers=_NO_STORE)
                incoming = users.get(payload.user_id)
                previous = db.scalars(select(HODAssignment).where(HODAssignment.user_id == payload.user_id)
                                      .order_by(HODAssignment.assigned_at.desc(), HODAssignment.id).limit(1)).first()
                if (incoming is None or incoming.role != UserRole.HOD or incoming.account_status != AccountStatus.ACTIVE
                        or previous is None or previous.ended_at is None):
                    raise HTTPException(409, "Choose an active HOD account without an assignment.", headers=_NO_STORE)
                name = incoming.hod_display_name or previous.full_name
            record_admin_change(db, actor_id, "hod_assignment", department_id, "update",
                                previous_user_id=str(current.user_id) if current else None,
                                user_id=str(payload.user_id) if payload.user_id else None)
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if current:
                current.ended_at, current.ended_by_user_id = max(now, current.assigned_at), actor_id
                db.flush()
            if payload.user_id:
                db.add(HODAssignment(department_id=department_id, user_id=payload.user_id, full_name=name,
                                     assigned_by_user_id=actor_id, assigned_at=now))
            for user in users.values():
                if user.account_status == AccountStatus.ACTIVE:
                    user.auth_version += 1
            for session in db.scalars(select(AuthSession).where(
                AuthSession.user_id.in_(affected), AuthSession.revoked_at.is_(None),
            ).with_for_update()):
                AuthSessionService._revoke_locked_session(db, session, now)
    except IntegrityError:
        raise HTTPException(409, "The HOD already has an active assignment.", headers=_NO_STORE) from None
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        raise HTTPException(503, "The HOD assignment could not be saved.", headers=_NO_STORE) from None


@router.put("/departments/{department_id}/hod", status_code=204, dependencies=_COOKIE_AUTH_GUARDS)
async def set_hod_mapping(department_id: UUID, request: Request, admin: Admin) -> Response:
    payload = await read_auth_json(request, HODMapping)
    if payload is None:
        raise HTTPException(422, "Choose an HOD or explicitly end the current assignment.", headers=_NO_STORE)
    await run_in_threadpool(_set_hod_mapping, department_id, payload, admin.user_id)
    return Response(status_code=204, headers=_NO_STORE)
