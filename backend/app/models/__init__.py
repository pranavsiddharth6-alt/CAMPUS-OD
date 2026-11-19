"""Campus OD Database Models Package.

Sri Krishna Arts and Science College (SKASC)
Exposes the models registered on Base.metadata.
"""
from app.models.enums import (
    AccountActionPurpose,
    AccountStatus,
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
    AccountActionToken,
    User,
    StudentProfile,
    TutorProfile,
    AdminProfile,
    AuthSession,
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
    "AccountActionPurpose",
    "AccountStatus",
    "UserRole",
    "ApplicationStatus",
    "EventCategory",
    "DaySession",
    "EventDayStatus",
    "DocumentType",
    "EvidenceReviewStatus",
    "NotificationType",
    # Models
    "AccountActionToken",
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
    "AuthSession",
    "RefreshToken",
]
