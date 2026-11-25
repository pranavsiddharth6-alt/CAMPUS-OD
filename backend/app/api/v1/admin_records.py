"""Local administrative record management and read-only OD oversight."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import joinedload
from starlette.concurrency import run_in_threadpool

from app.api.v1.admin_provisioning import Admin, local_demo_directory
from app.api.v1.auth import _COOKIE_AUTH_GUARDS, _NO_STORE, read_auth_json
from app.database.session import get_session_factory
from app.dependencies.auth import require_roles
from app.models.academic import AcademicYear, Class, ClassTutorAssignment, Department, HODAssignment, StudentClassEnrollment
from app.models.admin_audit import record_admin_change
from app.models.application import ODApplication
from app.models.enums import AccountStatus, ApplicationStatus, UserRole
from app.models.user import AdminProfile, StudentProfile, TutorProfile, User
from app.schemas.admin import ClassInput, DepartmentInput, EnrollmentEdit, FacultyEdit, NameEdit, StaffEdit, StudentEdit, YearInput
from app.services.od_applications import _detail, _summary

router = APIRouter(prefix="/admin", tags=["Local college data"],
                   dependencies=[Depends(require_roles(UserRole.ADMIN)), Depends(local_demo_directory)])

ACCOUNT_FIELDS = {
    UserRole.STUDENT: (StudentEdit, "student_profile"),
    UserRole.TUTOR: (FacultyEdit, "tutor_profile"),
    UserRole.HOD: (NameEdit, None),
    UserRole.ADMIN: (StaffEdit, "admin_profile"),
}
CATALOGS = {
    "departments": (Department, DepartmentInput),
    "classes": (Class, ClassInput),
    "academic-years": (AcademicYear, YearInput),
}


def fail(status, message):
    raise HTTPException(status, message, headers=_NO_STORE)


def run(operation, *args, write=False):
    try:
        factory = get_session_factory()
        with (factory.begin() if write else factory()) as db:
            return operation(db, *args)
    except IntegrityError:
        fail(409, "The record conflicts with existing college data.")
    except (SQLAlchemyError, OSError, RuntimeError):
        fail(503, "College data is temporarily unavailable.")


async def read_payload(request, schema):
    payload = await read_auth_json(request, schema)
    if payload is None:
        fail(422, "Check the required fields and their values.")
    return payload


def values(record, schema):
    return {name: getattr(record, name) for name in schema.model_fields}


def latest_hod(db, user_id):
    return db.scalars(select(HODAssignment).where(HODAssignment.user_id == user_id)
                      .order_by(HODAssignment.assigned_at.desc(), HODAssignment.id.desc()).limit(1)).first()


def account_view(db, user):
    schema, attribute = ACCOUNT_FIELDS[user.role]
    profile = getattr(user, attribute) if attribute else None
    data = values(profile, schema) if profile else {}
    if user.role == UserRole.HOD:
        assignment = latest_hod(db, user.id)
        data["full_name"] = user.hod_display_name or (assignment.full_name if assignment else user.email)
        data["department_id"] = assignment.department_id if assignment and assignment.ended_at is None else None
    if user.role == UserRole.STUDENT and profile:
        data["department_id"] = profile.department_id
        data["enrollments"] = [{"class_id": item.class_id, "academic_year_id": item.academic_year_id,
                                "is_active": item.is_active}
                               for item in sorted(profile.enrollments, key=lambda row: row.enrolled_at)]
    return {"id": user.id, "email": user.email, "role": user.role, "account_status": user.account_status, **data}


@router.get("/users")
def accounts(response: Response):
    response.headers.update(_NO_STORE)
    return run(lambda db: [account_view(db, user) for user in db.scalars(select(User).options(
        joinedload(User.student_profile).selectinload(StudentProfile.enrollments),
        joinedload(User.tutor_profile), joinedload(User.admin_profile),
    ).order_by(User.role, User.email))])


async def update_account(user_id, request, actor_id):
    role = await run_in_threadpool(run, lambda db: db.scalar(select(User.role).where(User.id == user_id)))
    if role is None:
        fail(404, "Account not found.")
    payload = await read_payload(request, ACCOUNT_FIELDS[role][0])

    def update(db):
        user = db.get(User, user_id, with_for_update=True)
        if user is None or user.role != role:
            fail(409, "The account changed. Refresh and try again.")
        _, attribute = ACCOUNT_FIELDS[role]
        data = payload.model_dump()
        if attribute is None:
            user.hod_display_name = payload.full_name
        else:
            profile = getattr(user, attribute)
            if profile is None:
                fail(409, "This account has no editable profile.")
            if role == UserRole.TUTOR and profile.department_id != payload.department_id:
                active_department(db, payload.department_id)
                if db.scalar(select(ClassTutorAssignment.id).where(
                    ClassTutorAssignment.tutor_id == profile.id, ClassTutorAssignment.is_active.is_(True),
                ).limit(1)):
                    fail(409, "Clear this faculty member’s active class assignments before changing departments.")
            for field, value in data.items():
                setattr(profile, field, value)
        record_admin_change(db, actor_id, role.value.lower(), user.id, "update", fields=list(data))
        db.flush()
        return account_view(db, user)

    return await run_in_threadpool(run, update, write=True)


@router.put("/users/{user_id}", dependencies=_COOKIE_AUTH_GUARDS)
async def edit_account(user_id: UUID, request: Request, response: Response, actor: Admin):
    response.headers.update(_NO_STORE)
    return await update_account(user_id, request, actor.user_id)


@router.post("/users/{user_id}/deactivate", status_code=204, dependencies=_COOKIE_AUTH_GUARDS)
def deactivate_account(user_id: UUID, actor: Admin):
    def deactivate(db):
        users = {row.id: row for row in db.scalars(select(User).where(
            User.id.in_([actor.user_id, user_id]),
        ).order_by(User.id).with_for_update())}
        administrator = users.get(actor.user_id)
        if administrator is None or administrator.account_status != AccountStatus.ACTIVE:
            fail(403, "An active administrator is required.")
        user = users.get(user_id)
        if user is None:
            fail(404, "Account not found.")
        if user.id == actor.user_id:
            fail(409, "You cannot deactivate your own administrator account.")
        if user.account_status == AccountStatus.DISABLED:
            return
        if user.role == UserRole.TUTOR and db.scalar(select(ODApplication.id).join(
            ODApplication.assigned_tutor,
        ).where(TutorProfile.user_id == user.id, ODApplication.status.not_in(
            (ApplicationStatus.OD_FINALIZED, ApplicationStatus.REJECTED),
        )).limit(1)):
            fail(409, "Resolve the faculty member’s open OD applications before deactivating the account.")
        previous = user.account_status
        user.account_status = AccountStatus.DISABLED
        # The existing migration trigger revokes sessions when an active account is disabled.
        if previous == AccountStatus.PENDING_ACTIVATION:
            user.auth_version += 1
        if user.role == UserRole.HOD:
            assignment = latest_hod(db, user.id)
            if assignment and assignment.ended_at is None:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                assignment.ended_at = max(now, assignment.assigned_at)
                assignment.ended_by_user_id = actor.user_id
                record_admin_change(db, actor.user_id, "hod_assignment", assignment.department_id, "update",
                                    previous_user_id=str(user.id), user_id=None)
        record_admin_change(db, actor.user_id, user.role.value.lower(), user.id, "deactivate", previous=previous.value)

    run(deactivate, write=True)
    return Response(status_code=204, headers=_NO_STORE)


def active_department(db, department_id):
    item = db.get(Department, department_id, with_for_update=True)
    if item is None or not item.is_active:
        fail(409, "Choose an active department.")
    return item


def save_catalog(db, kind, record_id, payload, actor_id):
    model, schema = CATALOGS[kind]
    if model is AcademicYear and db.bind.dialect.name == "postgresql":
        db.execute(text("LOCK TABLE academic_years IN SHARE ROW EXCLUSIVE MODE"))
    item = db.get(model, record_id, with_for_update=True) if record_id else model()
    if item is None:
        fail(404, "Academic record not found.")
    if model is Class:
        if record_id and (item.department_id != payload.department_id or item.academic_year_id != payload.academic_year_id):
            fail(409, "Create a new class to change its department or academic year.")
        if payload.is_active:
            active_department(db, payload.department_id)
        if db.get(AcademicYear, payload.academic_year_id) is None:
            fail(409, "Choose an existing academic year.")
    if model is Department and record_id and not payload.is_active:
        open_class = db.scalar(select(Class.id).where(Class.department_id == item.id, Class.is_active.is_(True)).limit(1))
        open_hod = db.scalar(select(HODAssignment.id).where(HODAssignment.department_id == item.id,
                                                           HODAssignment.ended_at.is_(None)).limit(1))
        if open_class or open_hod:
            fail(409, "Deactivate the department’s classes and end its HOD assignment first.")
    previous_current = []
    if model is AcademicYear and payload.is_current:
        previous_current = list(db.scalars(select(AcademicYear).where(AcademicYear.is_current.is_(True))))
        for year in previous_current:
            if year.id != record_id:
                year.is_current = False
                record_admin_change(db, actor_id, kind, year.id, "update", is_current=False)
    data = payload.model_dump()
    for field, value in data.items():
        setattr(item, field, value)
    db.add(item)
    db.flush()
    record_admin_change(db, actor_id, kind, item.id, "update" if record_id else "create",
                        fields=list(data), **({"is_active": data["is_active"]} if "is_active" in data else {}))
    return {"id": item.id, **values(item, schema)}


@router.get("/catalog")
def catalog(response: Response):
    response.headers.update(_NO_STORE)
    return run(lambda db: {kind: [{"id": row.id, **values(row, schema)}
                                 for row in db.scalars(select(model).order_by(model.name))]
                           for kind, (model, schema) in CATALOGS.items()})


async def change_catalog(kind, record_id, request, response, actor):
    if kind not in CATALOGS:
        fail(404, "Unknown academic record type.")
    payload = await read_payload(request, CATALOGS[kind][1])
    response.headers.update(_NO_STORE)
    return await run_in_threadpool(run, save_catalog, kind, record_id, payload, actor.user_id, write=True)


@router.post("/catalog/{kind}", status_code=201, dependencies=_COOKIE_AUTH_GUARDS)
async def create_catalog_record(kind: str, request: Request, response: Response, actor: Admin):
    return await change_catalog(kind, None, request, response, actor)


@router.put("/catalog/{kind}/{record_id}", dependencies=_COOKIE_AUTH_GUARDS)
async def edit_catalog_record(kind: str, record_id: UUID, request: Request, response: Response, actor: Admin):
    return await change_catalog(kind, record_id, request, response, actor)


@router.put("/students/{user_id}/enrollment", dependencies=_COOKIE_AUTH_GUARDS)
async def change_enrollment(user_id: UUID, request: Request, response: Response, actor: Admin):
    payload = await read_payload(request, EnrollmentEdit)
    response.headers.update(_NO_STORE)

    def save(db):
        student = db.scalar(select(StudentProfile).join(StudentProfile.user).where(
            User.id == user_id, User.role == UserRole.STUDENT,
        ).with_for_update(of=(StudentProfile, User)))
        item = db.get(Class, payload.class_id, with_for_update=True)
        if student is None or item is None:
            fail(404, "Student or class not found.")
        previous = db.scalar(select(StudentClassEnrollment).where(
            StudentClassEnrollment.student_id == student.id,
            StudentClassEnrollment.academic_year_id == item.academic_year_id,
        ))
        old_class_id = previous.class_id if previous else None
        if payload.is_active:
            active_department(db, item.department_id)
            if not item.is_active or student.user.account_status == AccountStatus.DISABLED:
                fail(409, "Choose an active class and a student account that is not disabled.")
            if item.academic_year.is_current:
                student.department_id = item.department_id
            elif student.department_id != item.department_id:
                fail(409, "Use a current-year enrollment to transfer a student between departments.")
            if previous is None:
                previous = StudentClassEnrollment(student_id=student.id, academic_year_id=item.academic_year_id)
                db.add(previous)
            previous.class_id = item.id
        elif previous is None or previous.class_id != item.id:
            fail(404, "The student does not have that enrollment.")
        previous.is_active = payload.is_active
        db.flush()
        record_admin_change(db, actor.user_id, "enrollment", previous.id, "update" if old_class_id else "create",
                            class_id=str(item.id), previous_class_id=str(old_class_id) if old_class_id else None,
                            is_active=payload.is_active)
        return account_view(db, student.user)

    return await run_in_threadpool(run, save, write=True)


@router.get("/metrics")
def metrics(response: Response):
    response.headers.update(_NO_STORE)

    def counts(db):
        accounts = {role.value: {status.value: 0 for status in AccountStatus} for role in UserRole}
        for role, status, count in db.execute(select(User.role, User.account_status, func.count()).group_by(
            User.role, User.account_status,
        )):
            accounts[role.value][status.value] = count
        departments = {True: 0, False: 0}
        departments.update(dict(db.execute(select(Department.is_active, func.count()).group_by(Department.is_active)).all()))
        applications = {status.value: 0 for status in ApplicationStatus}
        for status, count in db.execute(select(ODApplication.status, func.count()).group_by(ODApplication.status)):
            applications[status.value] = count
        return {"accounts": accounts, "departments": {"active": departments[True], "inactive": departments[False]},
                "applications": applications}

    return run(counts)


@router.get("/applications")
def applications(response: Response, offset: Annotated[int, Query(ge=0)] = 0):
    response.headers.update(_NO_STORE)
    return run(lambda db: [_summary(item) for item in db.scalars(select(ODApplication).options(
        joinedload(ODApplication.student), joinedload(ODApplication.assigned_tutor),
    ).order_by(ODApplication.created_at.desc(), ODApplication.id.desc()).offset(offset).limit(50))])


@router.get("/applications/{application_id}")
def application(application_id: UUID, response: Response):
    response.headers.update(_NO_STORE)

    def detail(db):
        item = db.get(ODApplication, application_id)
        if item is None:
            fail(404, "Application not found.")
        department = db.get(Department, item.department_id) if item.department_id else None
        hod = db.scalar(select(HODAssignment).where(HODAssignment.department_id == item.department_id,
                                                     HODAssignment.ended_at.is_(None))) if department else None
        data = _detail(item, include_documents=False).model_dump(exclude={"documents", "revision", "expected_venue"})
        return {**data, "department_name": department.name if department else None,
                "current_hod_name": (db.get(User, hod.user_id).hod_display_name or hod.full_name) if hod else None}

    return run(detail)
