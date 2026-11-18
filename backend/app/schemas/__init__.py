from app.schemas.health import DatabaseHealthResponse, SystemHealthResponse
from app.schemas.user import (
    UserBase,
    UserCreate,
    UserResponse,
    StudentProfileResponse,
    TutorProfileResponse,
    AdminProfileResponse,
)
from app.schemas.academic import (
    DepartmentBase,
    DepartmentResponse,
    AcademicYearBase,
    AcademicYearResponse,
    ClassBase,
    ClassResponse,
)
from app.schemas.application import (
    ODApplicationCreate,
    ODApplicationResponse,
    EventDayCreate,
    EventDayResponse,
    StatusHistoryResponse,
)
from app.schemas.evidence import (
    StoredFileResponse,
    LocationCaptureCreate,
    LocationCaptureResponse,
    EvidenceSubmissionResponse,
    EvidenceReviewCreate,
    EvidenceReviewResponse,
)

__all__ = [
    "DatabaseHealthResponse",
    "SystemHealthResponse",
    "UserBase",
    "UserCreate",
    "UserResponse",
    "StudentProfileResponse",
    "TutorProfileResponse",
    "AdminProfileResponse",
    "DepartmentBase",
    "DepartmentResponse",
    "AcademicYearBase",
    "AcademicYearResponse",
    "ClassBase",
    "ClassResponse",
    "ODApplicationCreate",
    "ODApplicationResponse",
    "EventDayCreate",
    "EventDayResponse",
    "StatusHistoryResponse",
    "StoredFileResponse",
    "LocationCaptureCreate",
    "LocationCaptureResponse",
    "EvidenceSubmissionResponse",
    "EvidenceReviewCreate",
    "EvidenceReviewResponse",
]
