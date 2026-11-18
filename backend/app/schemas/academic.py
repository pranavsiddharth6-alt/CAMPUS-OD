import uuid
from datetime import date
from typing import Optional
from pydantic import BaseModel


class DepartmentBase(BaseModel):
    code: str
    name: str


class DepartmentResponse(DepartmentBase):
    id: uuid.UUID

    class Config:
        from_attributes = True


class AcademicYearBase(BaseModel):
    name: str
    start_date: date
    end_date: date
    is_current: bool = False


class AcademicYearResponse(AcademicYearBase):
    id: uuid.UUID

    class Config:
        from_attributes = True


class ClassBase(BaseModel):
    name: str
    department_id: uuid.UUID
    academic_year_id: uuid.UUID
    batch: str
    semester: int
    section: str = "A"


class ClassResponse(ClassBase):
    id: uuid.UUID

    class Config:
        from_attributes = True
