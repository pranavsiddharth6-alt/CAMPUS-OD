import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr
from app.models.enums import UserRole


class UserBase(BaseModel):
    email: EmailStr
    role: UserRole
    is_active: bool = True


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StudentProfileResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    roll_number: str
    register_number: str
    full_name: str
    phone_number: Optional[str] = None
    department_id: uuid.UUID

    class Config:
        from_attributes = True


class TutorProfileResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    staff_id: str
    full_name: str
    designation: str
    phone_number: Optional[str] = None
    department_id: uuid.UUID

    class Config:
        from_attributes = True


class AdminProfileResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    staff_id: str
    full_name: str
    designation: str

    class Config:
        from_attributes = True
