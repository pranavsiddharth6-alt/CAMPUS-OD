"""Read demo academic records and manage class-tutor mappings on localhost."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, selectinload
from starlette.concurrency import run_in_threadpool

from app.api.v1.admin_provisioning import local_demo_directory
from app.api.v1.auth import _COOKIE_AUTH_GUARDS, _NO_STORE, read_auth_json
from app.database.session import get_session_factory
from app.dependencies.auth import require_roles
from app.models.academic import Class, ClassTutorAssignment, StudentClassEnrollment
from app.models.enums import AccountStatus, UserRole
from app.models.user import TutorProfile, User

router = APIRouter(
    prefix="/admin/academics", tags=["Local demo administration"],
    dependencies=[Depends(require_roles(UserRole.ADMIN)), Depends(local_demo_directory)],
)


class TutorMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    tutor_id: UUID | None


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


def _set_mapping(class_id: UUID, payload: TutorMapping) -> None:
    try:
        with get_session_factory().begin() as db:
            item = db.scalar(select(Class).where(Class.id == class_id).with_for_update())
            if item is None:
                raise HTTPException(404, "Class not found.", headers=_NO_STORE)
            existing = db.scalar(select(ClassTutorAssignment).where(
                ClassTutorAssignment.class_id == item.id, ClassTutorAssignment.academic_year_id == item.academic_year_id,
            ).with_for_update())
            if payload.tutor_id is None:
                if existing is not None:
                    existing.is_active = False
                return
            tutor = db.scalar(select(TutorProfile.id).join(TutorProfile.user).where(
                TutorProfile.id == payload.tutor_id, TutorProfile.department_id == item.department_id,
                User.role == UserRole.TUTOR, User.account_status == AccountStatus.ACTIVE,
            ).with_for_update(read=True, of=(TutorProfile, User)))
            if tutor is None:
                raise HTTPException(409, "Choose an active tutor in this class’s department.", headers=_NO_STORE)
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
async def set_mapping(class_id: UUID, request: Request) -> Response:
    payload = await read_auth_json(request, TutorMapping)
    if payload is None:
        raise HTTPException(422, "Choose a tutor or explicitly clear the mapping.", headers=_NO_STORE)
    await run_in_threadpool(_set_mapping, class_id, payload)
    return Response(status_code=204, headers=_NO_STORE)
