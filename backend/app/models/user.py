"""User and Profile models for Campus OD.

Sri Krishna Arts and Science College (SKASC)
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Enum as SQLEnum,
    Index,
    Integer,
    LargeBinary,
    UniqueConstraint,
    and_,
    column,
    func,
    or_,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.session import Base
from app.models.enums import AccountActionPurpose, AccountStatus, UserRole

_ARGON2ID_FORMAT = (
    r"^[$]argon2id[$]v=19[$]m=[1-9][0-9]*,t=[1-9][0-9]*,p=[1-9][0-9]*"
    r"[$][A-Za-z0-9+/]+[$][A-Za-z0-9+/]+$"
)


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hod_display_name = Column(String(150), nullable=True)
    hashed_password = Column(String(255), nullable=True)
    role = Column(SQLEnum(UserRole, name="user_role_enum"), nullable=False, index=True)
    account_status = Column(
        SQLEnum(AccountStatus, name="account_status_enum", create_constraint=True),
        server_default=AccountStatus.PENDING_ACTIVATION.value,
        nullable=False,
    )
    is_active = Column(Boolean, Computed("account_status = 'ACTIVE'", persisted=True), nullable=False)
    auth_version = Column(Integer, server_default=text("0"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint(
            or_(
                column("account_status") != AccountStatus.ACTIVE.value,
                and_(column("hashed_password").is_not(None), column("hashed_password").regexp_match(_ARGON2ID_FORMAT)),
            ),
            name="ck_users_active_password_hash",
        ),
        CheckConstraint(
            "account_status <> 'PENDING_ACTIVATION' OR hashed_password IS NULL",
            name="ck_users_pending_without_password",
        ),
        CheckConstraint("auth_version >= 0", name="ck_users_auth_version"),
    )

    # Relationships
    student_profile = relationship("StudentProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    tutor_profile = relationship("TutorProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    admin_profile = relationship("AdminProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    auth_sessions = relationship("AuthSession", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    account_action_tokens = relationship(
        "AccountActionToken", back_populates="user", cascade="all, delete-orphan", passive_deletes=True,
    )
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    roll_number = Column(String(50), unique=True, nullable=False, index=True)
    gender = Column(String(6), CheckConstraint("gender IN ('MALE', 'FEMALE')", name="ck_student_gender"))
    accommodation = Column(String(15), CheckConstraint(
        "accommodation IN ('COLLEGE_HOSTEL', 'OUTSIDE_STAYING', 'GUARDIAN', 'OTHER')",
        name="ck_student_accommodation",
    ))
    register_number = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    phone_number = Column(String(20), nullable=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="student_profile")
    department = relationship("Department", back_populates="students")
    enrollments = relationship("StudentClassEnrollment", back_populates="student", cascade="all, delete-orphan")
    applications = relationship("ODApplication", back_populates="student")


class TutorProfile(Base):
    __tablename__ = "tutor_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    staff_id = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    designation = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=True)
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="tutor_profile")
    department = relationship("Department", back_populates="tutors")
    class_assignments = relationship("ClassTutorAssignment", back_populates="tutor")
    assigned_applications = relationship("ODApplication", back_populates="assigned_tutor")
    reviews = relationship("EvidenceReview", back_populates="reviewer")


class AdminProfile(Base):
    __tablename__ = "admin_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    staff_id = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(150), nullable=False)
    designation = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="admin_profile")


class AccountActionToken(Base):
    """A digest-only, purpose-bound invitation or password-reset credential."""

    __tablename__ = "account_action_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(
        SQLEnum(AccountActionPurpose, name="account_action_purpose_enum", create_constraint=True), nullable=False,
    )
    token_digest = Column(LargeBinary(32), nullable=False)
    auth_version = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    invalidated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("token_digest", name="uq_account_action_tokens_digest"),
        CheckConstraint("length(token_digest) = 32", name="ck_account_action_tokens_digest_length"),
        CheckConstraint("auth_version >= 0", name="ck_account_action_tokens_auth_version"),
        CheckConstraint("expires_at > created_at", name="ck_account_action_tokens_expiry"),
        CheckConstraint(
            "consumed_at IS NULL OR (consumed_at >= created_at AND consumed_at < expires_at AND invalidated_at IS NULL)",
            name="ck_account_action_tokens_consumption",
        ),
        CheckConstraint(
            "invalidated_at IS NULL OR invalidated_at >= created_at", name="ck_account_action_tokens_invalidation",
        ),
        Index(
            "uq_account_action_tokens_outstanding", "user_id", "purpose", unique=True,
            postgresql_where=text("consumed_at IS NULL AND invalidated_at IS NULL"),
            sqlite_where=text("consumed_at IS NULL AND invalidated_at IS NULL"),
        ),
    )

    user = relationship("User", back_populates="account_action_tokens")


class AuthSession(Base):
    """Revocable session with UTC timestamps and a family of refresh tokens."""

    __tablename__ = "auth_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=text("timezone('UTC', now())"), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_auth_sessions_id_user_id"),
        CheckConstraint("expires_at >= created_at", name="ck_auth_sessions_expiry_order"),
        CheckConstraint("revoked_at >= created_at", name="ck_auth_sessions_revocation_order"),
    )

    user = relationship("User", back_populates="auth_sessions")
    # The database checks the owner as well. The user relationship manages user_id.
    refresh_tokens = relationship(
        "RefreshToken",
        primaryjoin="AuthSession.id == foreign(RefreshToken.session_id)",
        back_populates="auth_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    session_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # Set only on rotation. Logout/revocation leaves an unconsumed token's marker unset.
    consumed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ("session_id", "user_id"),
            ("auth_sessions.id", "auth_sessions.user_id"),
            name="fk_refresh_tokens_session_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "consumed_at IS NULL OR (is_revoked AND consumed_at >= created_at AND consumed_at < expires_at)",
            name="ck_refresh_tokens_consumption",
        ),
        Index(
            "uq_refresh_tokens_one_unrevoked_per_session",
            "session_id",
            unique=True,
            postgresql_where=text("is_revoked IS FALSE"),
            sqlite_where=text("is_revoked IS FALSE"),
        ),
    )

    user = relationship("User", back_populates="refresh_tokens")
    auth_session = relationship(
        "AuthSession",
        primaryjoin="AuthSession.id == foreign(RefreshToken.session_id)",
        back_populates="refresh_tokens",
    )
