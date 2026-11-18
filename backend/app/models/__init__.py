"""Campus OD Database Models Package.

Sri Krishna Arts and Science College (SKASC)
Exposes all 19 Core Entities registered on Base.metadata.
"""
from app.models.enums import (
    UserRole,
    ApplicationStatus,
    EventCategory,
    DaySession,
    EventDayStatus,
    DocumentType,
    EvidenceReviewStatus,
    NotificationType,
)
from app.models.user import (
    User,
    StudentProfile,
    TutorProfile,
    AdminProfile,
    RefreshToken,
)
from app.models.academic import (
    Department,
    AcademicYear,
    Class,
    StudentClassEnrollment,
    ClassTutorAssignment,
)
from app.models.application import (
    ODApplication,
    EventDay,
    ApplicationStatusHistory,
)
from app.models.evidence import (
    StoredFile,
    ApplicationDocument,
    EvidenceSubmission,
    LocationCapture,
    EvidenceReview,
)
from app.models.notification import Notification

__all__ = [
    # Enums
    "UserRole",
    "ApplicationStatus",
    "EventCategory",
    "DaySession",
    "EventDayStatus",
    "DocumentType",
    "EvidenceReviewStatus",
    "NotificationType",
    # 19 Core Entities
    "User",
    "Department",
    "AcademicYear",
    "Class",
    "StudentProfile",
    "TutorProfile",
    "AdminProfile",
    "StudentClassEnrollment",
    "ClassTutorAssignment",
    "ODApplication",
    "EventDay",
    "StoredFile",
    "ApplicationDocument",
    "EvidenceSubmission",
    "LocationCapture",
    "EvidenceReview",
    "ApplicationStatusHistory",
    "Notification",
    "RefreshToken",
]
