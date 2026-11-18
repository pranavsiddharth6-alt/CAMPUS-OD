"""Academic structure models for Campus OD.

Sri Krishna Arts and Science College (SKASC)
Defines Departments, Academic Years, Classes, Enrollments, and Tutor Assignments.
"""
import uuid
from datetime import datetime, date
from sqlalchemy import (
    CheckConstraint,
    Column,
    String,
    Boolean,
    DateTime,
    Date,
    Integer,
    ForeignKey,
    ForeignKeyConstraint,
    UniqueConstraint,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database.session import Base


class Department(Base):
    __tablename__ = "departments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(150), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    classes = relationship("Class", back_populates="department")
    students = relationship("StudentProfile", back_populates="department")
    tutors = relationship("TutorProfile", back_populates="department")


class AcademicYear(Base):
    __tablename__ = "academic_years"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), unique=True, nullable=False, index=True)  # e.g., "2026-2027"
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_current = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_academic_year_date_order"),
    )

    classes = relationship("Class", back_populates="academic_year")
    enrollments = relationship("StudentClassEnrollment", back_populates="academic_year")
    tutor_assignments = relationship("ClassTutorAssignment", back_populates="academic_year")


class Class(Base):
    __tablename__ = "classes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)  # e.g., "B.Sc Computer Science - Year III - Sec A"
    department_id = Column(UUID(as_uuid=True), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True)
    academic_year_id = Column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    batch = Column(String(20), nullable=False)  # e.g., "2023-2026"
    semester = Column(Integer, nullable=False)
    section = Column(String(10), nullable=False, default="A")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "academic_year_id", name="uq_class_name_academic_year"),
        UniqueConstraint("id", "academic_year_id", name="uq_class_id_academic_year"),
    )

    department = relationship("Department", back_populates="classes")
    academic_year = relationship("AcademicYear", back_populates="classes")
    # The composite foreign keys enforce the year. The class relationship writes only class_id.
    enrollments = relationship(
        "StudentClassEnrollment",
        primaryjoin="Class.id == foreign(StudentClassEnrollment.class_id)",
        back_populates="assigned_class",
    )
    tutor_assignments = relationship(
        "ClassTutorAssignment",
        primaryjoin="Class.id == foreign(ClassTutorAssignment.class_id)",
        back_populates="assigned_class",
    )


class StudentClassEnrollment(Base):
    __tablename__ = "student_class_enrollments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(UUID(as_uuid=True), ForeignKey("student_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    academic_year_id = Column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    enrolled_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("student_id", "academic_year_id", name="uq_student_academic_year_enrollment"),
        ForeignKeyConstraint(
            ("class_id", "academic_year_id"),
            ("classes.id", "classes.academic_year_id"),
            name="fk_enrollment_class_academic_year",
            ondelete="RESTRICT",
        ),
    )

    student = relationship("StudentProfile", back_populates="enrollments")
    assigned_class = relationship(
        "Class",
        primaryjoin="Class.id == foreign(StudentClassEnrollment.class_id)",
        back_populates="enrollments",
    )
    academic_year = relationship("AcademicYear", back_populates="enrollments")


class ClassTutorAssignment(Base):
    __tablename__ = "class_tutor_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tutor_id = Column(UUID(as_uuid=True), ForeignKey("tutor_profiles.id", ondelete="RESTRICT"), nullable=False, index=True)
    class_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    academic_year_id = Column(UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="RESTRICT"), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("class_id", "academic_year_id", name="uq_class_academic_year_tutor"),
        ForeignKeyConstraint(
            ("class_id", "academic_year_id"),
            ("classes.id", "classes.academic_year_id"),
            name="fk_tutor_assignment_class_academic_year",
            ondelete="RESTRICT",
        ),
    )

    tutor = relationship("TutorProfile", back_populates="class_assignments")
    assigned_class = relationship(
        "Class",
        primaryjoin="Class.id == foreign(ClassTutorAssignment.class_id)",
        back_populates="tutor_assignments",
    )
    academic_year = relationship("AcademicYear", back_populates="tutor_assignments")
