"""Inputs for college-managed student and tutor provisioning."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints


_Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
_FullName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
_Designation = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class _ProvisioningIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, frozen=True)

    email: EmailStr = Field(max_length=255)
    full_name: _FullName
    department_id: UUID


class StudentProvisioningRequest(_ProvisioningIdentity):
    roll_number: _Identifier
    register_number: _Identifier
    class_id: UUID
    gender: Literal["MALE", "FEMALE"] | None = None
    accommodation: Literal["COLLEGE_HOSTEL", "OUTSIDE_STAYING", "GUARDIAN", "OTHER"] | None = None


class TutorProvisioningRequest(_ProvisioningIdentity):
    staff_id: _Identifier
    designation: _Designation


class HODProvisioningRequest(_ProvisioningIdentity):
    pass


class ApprovedHODRecord(HODProvisioningRequest):
    """A backend-supplied record from the approved staff roster."""


class ApprovedStudentRecord(StudentProvisioningRequest):
    """A backend-supplied roster record with its approved academic year."""

    academic_year_id: UUID


class ApprovedTutorRecord(TutorProvisioningRequest):
    """A backend-supplied record from the approved staff roster."""


class DemoRosterResponse(BaseModel):
    students: list[StudentProvisioningRequest]
    tutors: list[TutorProvisioningRequest]
    hods: list[HODProvisioningRequest]


class ProvisioningResponse(BaseModel):
    user_id: UUID
    profile_id: UUID
    invitation_id: UUID
    invitation_delivered: bool
