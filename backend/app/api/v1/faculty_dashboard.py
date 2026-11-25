"""Class statistics for the authenticated faculty member."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import get_session_factory
from app.dependencies.auth import AuthenticatedUser, require_roles
from app.models.academic import AcademicYear, Class, ClassTutorAssignment, Department, StudentClassEnrollment
from app.models.enums import AccountStatus, UserRole
from app.models.user import StudentProfile, TutorProfile, User

router = APIRouter(prefix="/tutor", tags=["Faculty dashboard"])
Faculty = Annotated[AuthenticatedUser, Depends(require_roles(UserRole.TUTOR))]
NO_STORE = {"Cache-Control": "no-store"}


class FacultyClass(BaseModel):
    id: UUID
    name: str
    department: str
    academic_year: str


class StudentCounts(BaseModel):
    total: int = 0
    boys: int = 0
    girls: int = 0


class ClassStatistics(BaseModel):
    total_students: StudentCounts
    hostel_students: StudentCounts
    outside_staying: StudentCounts
    guardian: StudentCounts


class FacultyDashboard(BaseModel):
    classes: list[FacultyClass]
    selected_class_id: UUID | None = None
    statistics: ClassStatistics | None = None


def assigned_classes(user_id):
    return (
        select(Class.id, Class.name, Department.name.label("department"),
               AcademicYear.name.label("academic_year"), Class.department_id, Class.academic_year_id)
        .join(Department, Department.id == Class.department_id)
        .join(AcademicYear, AcademicYear.id == Class.academic_year_id)
        .join(ClassTutorAssignment, and_(
            ClassTutorAssignment.class_id == Class.id,
            ClassTutorAssignment.academic_year_id == Class.academic_year_id,
        ))
        .join(TutorProfile, TutorProfile.id == ClassTutorAssignment.tutor_id)
        .join(User, User.id == TutorProfile.user_id)
        .where(User.id == user_id, User.role == UserRole.TUTOR, User.account_status == AccountStatus.ACTIVE,
               TutorProfile.department_id == Class.department_id, ClassTutorAssignment.is_active.is_(True),
               Class.is_active.is_(True), Department.is_active.is_(True), AcademicYear.is_current.is_(True))
    )


def class_statistics(db, scoped_classes, class_id):
    student = (
        select(StudentClassEnrollment.class_id, StudentClassEnrollment.academic_year_id, StudentProfile.department_id,
               StudentProfile.id, StudentProfile.gender, StudentProfile.accommodation)
        .join(StudentProfile, StudentProfile.id == StudentClassEnrollment.student_id)
        .join(User, User.id == StudentProfile.user_id)
        .where(StudentClassEnrollment.class_id == class_id, StudentClassEnrollment.is_active.is_(True),
               User.role == UserRole.STUDENT)
        .subquery()
    )
    rows = db.execute(
        select(student.c.gender, student.c.accommodation, func.count(student.c.id.distinct()))
        .select_from(scoped_classes)
        .outerjoin(student, and_(student.c.class_id == scoped_classes.c.id,
                                 student.c.academic_year_id == scoped_classes.c.academic_year_id,
                                 student.c.department_id == scoped_classes.c.department_id))
        .where(scoped_classes.c.id == class_id)
        .group_by(student.c.gender, student.c.accommodation)
    ).all()
    if not rows:
        raise HTTPException(404, "Class not found in your active assignments.", headers=NO_STORE)

    total = StudentCounts()
    accommodation_counts = {key: StudentCounts() for key in ("COLLEGE_HOSTEL", "OUTSIDE_STAYING", "GUARDIAN")}
    for gender, accommodation, count in rows:
        total.total += count
        total.boys += count if gender == "MALE" else 0
        total.girls += count if gender == "FEMALE" else 0
        category = accommodation_counts.get(accommodation)
        if category:
            category.total += count
            category.boys += count if gender == "MALE" else 0
            category.girls += count if gender == "FEMALE" else 0
    return ClassStatistics(
        total_students=total, hostel_students=accommodation_counts["COLLEGE_HOSTEL"],
        outside_staying=accommodation_counts["OUTSIDE_STAYING"], guardian=accommodation_counts["GUARDIAN"],
    )


@router.get("/dashboard")
def dashboard(response: Response, user: Faculty, class_id: UUID | None = None) -> FacultyDashboard:
    response.headers.update(NO_STORE)
    try:
        with get_session_factory()() as db:
            scope = assigned_classes(user.user_id)
            classes = [FacultyClass.model_validate(row) for row in db.execute(
                scope.order_by(Class.name, Class.id)
            ).mappings()]
            if class_id is not None and all(item.id != class_id for item in classes):
                raise HTTPException(404, "Class not found in your active assignments.", headers=NO_STORE)
            if not classes:
                return FacultyDashboard(classes=[])
            selected = class_id or classes[0].id
            return FacultyDashboard(classes=classes, selected_class_id=selected,
                                    statistics=class_statistics(db, scope.subquery(), selected))
    except (SQLAlchemyError, OSError, RuntimeError, ValueError):
        raise HTTPException(503, "Class statistics are temporarily unavailable.", headers=NO_STORE) from None
