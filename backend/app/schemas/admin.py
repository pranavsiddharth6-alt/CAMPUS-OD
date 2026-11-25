from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, model_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class AdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class NameEdit(AdminInput):
    full_name: Name


class StaffEdit(NameEdit):
    staff_id: Identifier
    designation: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class AdminInvite(StaffEdit):
    email: EmailStr = Field(max_length=255)


class FacultyEdit(StaffEdit):
    department_id: UUID


class StudentEdit(NameEdit):
    roll_number: Identifier
    register_number: Identifier
    gender: Literal["MALE", "FEMALE"] | None
    accommodation: Literal["COLLEGE_HOSTEL", "OUTSIDE_STAYING", "GUARDIAN", "OTHER"] | None


class EnrollmentEdit(AdminInput):
    class_id: UUID
    is_active: bool


class DepartmentInput(AdminInput):
    code: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=20)]
    name: Name
    is_active: bool


class ClassInput(AdminInput):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    department_id: UUID
    academic_year_id: UUID
    batch: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
    semester: int = Field(ge=1)
    section: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10)]
    is_active: bool


class YearInput(AdminInput):
    name: Identifier
    start_date: date
    end_date: date
    is_current: bool

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_date < self.start_date:
            raise ValueError("End date must follow start date.")
        return self
