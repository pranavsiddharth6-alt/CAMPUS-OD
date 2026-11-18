"""0001 Initial Schema for Campus OD

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-11-17 21:55:00.000000

Sri Krishna Arts and Science College (SKASC)
Defines all 19 core entities:
1. users
2. departments
3. academic_years
4. classes
5. student_profiles
6. tutor_profiles
7. admin_profiles
8. student_class_enrollments
9. class_tutor_assignments
10. od_applications
11. event_days
12. stored_files
13. application_documents
14. evidence_submissions
15. location_captures
16. evidence_reviews
17. application_status_history
18. notifications
19. refresh_tokens
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

application_status_type = postgresql.ENUM(
    'SUBMITTED',
    'UNDER_TUTOR_REVIEW',
    'PRE_APPROVED',
    'AWAITING_PARTICIPATION_PROOF',
    'UNDER_FINAL_VERIFICATION',
    'OD_FINALIZED',
    'REJECTED',
    'CORRECTION_REQUESTED',
    name='application_status_enum',
    create_type=False,
)

protected_tables = (
    'users', 'departments', 'academic_years', 'classes', 'student_profiles',
    'tutor_profiles', 'admin_profiles', 'student_class_enrollments',
    'class_tutor_assignments', 'od_applications', 'event_days', 'stored_files',
    'application_documents', 'evidence_submissions', 'location_captures',
    'evidence_reviews', 'application_status_history', 'notifications',
    'refresh_tokens', 'alembic_version',
)


def restrict_client_access() -> None:
    # Only Campus OD tables are affected. The migration role retains owner access.
    table_literals = ', '.join(f"'{table}'" for table in protected_tables)
    op.execute(f"""
        DO $campus_od_access$
        DECLARE
            table_name text;
            client_role text;
            table_privileges text := 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER';
        BEGIN
            IF current_setting('server_version_num')::integer >= 170000 THEN
                table_privileges := table_privileges || ', MAINTAIN';
            END IF;

            FOREACH table_name IN ARRAY ARRAY[{table_literals}]
            LOOP
                EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
                EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM PUBLIC', table_name);

                FOR client_role IN
                    SELECT rolname FROM pg_catalog.pg_roles WHERE rolname IN ('anon', 'authenticated')
                LOOP
                    EXECUTE format(
                        'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I', table_name, client_role
                    );
                END LOOP;

                SELECT rolname INTO client_role
                FROM pg_catalog.pg_roles
                WHERE rolname IN ('anon', 'authenticated')
                  AND has_table_privilege(oid, to_regclass(format('public.%I', table_name)), table_privileges)
                LIMIT 1;
                IF FOUND THEN
                    RAISE EXCEPTION 'Role % still has privileges on public.% through another grant or role',
                        client_role, table_name;
                END IF;
            END LOOP;
        END;
        $campus_od_access$
    """)


def upgrade() -> None:
    op.execute('SET LOCAL search_path TO public')

    # 1. users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('role', sa.Enum('STUDENT', 'TUTOR', 'ADMIN', name='user_role_enum'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)
    op.create_index('ix_users_role', 'users', ['role'])

    # 2. departments table
    op.create_table(
        'departments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=150), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_departments_code', 'departments', ['code'], unique=True)

    # 3. academic_years table
    op.create_table(
        'academic_years',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('is_current', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('end_date >= start_date', name='ck_academic_year_date_order'),
    )
    op.create_index('ix_academic_years_name', 'academic_years', ['name'], unique=True)
    op.create_index('ix_academic_years_is_current', 'academic_years', ['is_current'])

    # 4. classes table
    op.create_table(
        'classes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('department_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('academic_year_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('academic_years.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('batch', sa.String(length=20), nullable=False),
        sa.Column('semester', sa.Integer(), nullable=False),
        sa.Column('section', sa.String(length=10), server_default='A', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint('name', 'academic_year_id', name='uq_class_name_academic_year'),
        sa.UniqueConstraint('id', 'academic_year_id', name='uq_class_id_academic_year'),
    )
    op.create_index('ix_classes_department_id', 'classes', ['department_id'])
    op.create_index('ix_classes_academic_year_id', 'classes', ['academic_year_id'])

    # 5. student_profiles table
    op.create_table(
        'student_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('roll_number', sa.String(length=50), nullable=False),
        sa.Column('register_number', sa.String(length=50), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('phone_number', sa.String(length=20), nullable=True),
        sa.Column('department_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_student_profiles_roll_number', 'student_profiles', ['roll_number'], unique=True)
    op.create_index('ix_student_profiles_register_number', 'student_profiles', ['register_number'], unique=True)
    op.create_index('ix_student_profiles_department_id', 'student_profiles', ['department_id'])

    # 6. tutor_profiles table
    op.create_table(
        'tutor_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('staff_id', sa.String(length=50), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('designation', sa.String(length=100), nullable=False),
        sa.Column('phone_number', sa.String(length=20), nullable=True),
        sa.Column('department_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('departments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_tutor_profiles_staff_id', 'tutor_profiles', ['staff_id'], unique=True)
    op.create_index('ix_tutor_profiles_department_id', 'tutor_profiles', ['department_id'])

    # 7. admin_profiles table
    op.create_table(
        'admin_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('staff_id', sa.String(length=50), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('designation', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    op.create_index('ix_admin_profiles_staff_id', 'admin_profiles', ['staff_id'], unique=True)

    # 8. student_class_enrollments table
    op.create_table(
        'student_class_enrollments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('student_profiles.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('class_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('academic_year_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('academic_years.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('enrolled_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('student_id', 'academic_year_id', name='uq_student_academic_year_enrollment'),
        sa.ForeignKeyConstraint(
            ('class_id', 'academic_year_id'), ('classes.id', 'classes.academic_year_id'),
            name='fk_enrollment_class_academic_year', ondelete='RESTRICT',
        ),
    )
    op.create_index('ix_student_class_enrollments_student_id', 'student_class_enrollments', ['student_id'])
    op.create_index('ix_student_class_enrollments_class_id', 'student_class_enrollments', ['class_id'])
    op.create_index('ix_student_class_enrollments_academic_year_id', 'student_class_enrollments', ['academic_year_id'])

    # 9. class_tutor_assignments table
    op.create_table(
        'class_tutor_assignments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tutor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tutor_profiles.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('class_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('academic_year_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('academic_years.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('class_id', 'academic_year_id', name='uq_class_academic_year_tutor'),
        sa.ForeignKeyConstraint(
            ('class_id', 'academic_year_id'), ('classes.id', 'classes.academic_year_id'),
            name='fk_tutor_assignment_class_academic_year', ondelete='RESTRICT',
        ),
    )
    op.create_index('ix_class_tutor_assignments_tutor_id', 'class_tutor_assignments', ['tutor_id'])
    op.create_index('ix_class_tutor_assignments_class_id', 'class_tutor_assignments', ['class_id'])
    op.create_index('ix_class_tutor_assignments_academic_year_id', 'class_tutor_assignments', ['academic_year_id'])

    # 10. od_applications table
    application_status_type.create(op.get_bind(), checkfirst=False)
    op.create_table(
        'od_applications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_number', sa.String(length=50), nullable=False),
        sa.Column('student_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('student_profiles.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('assigned_tutor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tutor_profiles.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('event_name', sa.String(length=200), nullable=False),
        sa.Column('event_category', sa.Enum('TECHNICAL', 'SPORTS', 'CULTURAL', 'ACADEMIC', 'PAPER_PRESENTATION', 'NSS_NCC', 'OTHER', name='event_category_enum'), nullable=False),
        sa.Column('host_institution', sa.String(length=200), nullable=False),
        sa.Column('venue_location', sa.String(length=255), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('total_days', sa.Integer(), server_default='1', nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', application_status_type, server_default='SUBMITTED', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.CheckConstraint('end_date >= start_date', name='ck_od_application_date_order'),
        sa.CheckConstraint('total_days > 0', name='ck_od_application_total_days_positive'),
    )
    op.create_index('ix_od_applications_application_number', 'od_applications', ['application_number'], unique=True)
    op.create_index('ix_od_applications_student_id', 'od_applications', ['student_id'])
    op.create_index('ix_od_applications_assigned_tutor_id', 'od_applications', ['assigned_tutor_id'])
    op.create_index('ix_od_applications_status', 'od_applications', ['status'])
    op.create_index('ix_od_applications_start_date', 'od_applications', ['start_date'])
    op.create_index('ix_od_applications_event_name', 'od_applications', ['event_name'])
    op.create_index('ix_od_applications_end_date', 'od_applications', ['end_date'])
    op.create_index('ix_od_applications_created_at', 'od_applications', ['created_at'])

    # 11. event_days table
    op.create_table(
        'event_days',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('od_applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('is_full_day', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('session', sa.Enum('FULL_DAY', 'FORENOON', 'AFTERNOON', name='day_session_enum'), server_default='FULL_DAY', nullable=False),
        sa.Column('day_status', sa.Enum('PENDING', 'VERIFIED', 'REJECTED', name='event_day_status_enum'), server_default='PENDING', nullable=False),
        sa.Column('verification_notes', sa.Text(), nullable=True),
        sa.UniqueConstraint('application_id', 'event_date', name='uq_event_day_application_date'),
    )
    op.create_index('ix_event_days_application_id', 'event_days', ['application_id'])
    op.create_index('ix_event_days_event_date', 'event_days', ['event_date'])
    op.create_index('ix_event_days_day_status', 'event_days', ['day_status'])

    # 12. stored_files table
    op.create_table(
        'stored_files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('file_size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('sha256_checksum', sa.String(length=64), nullable=False),
        sa.Column('uploaded_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('file_size_bytes >= 0', name='ck_stored_file_size_nonnegative'),
    )
    op.create_index('ix_stored_files_storage_key', 'stored_files', ['storage_key'], unique=True)
    op.create_index('ix_stored_files_sha256_checksum', 'stored_files', ['sha256_checksum'])
    op.create_index('ix_stored_files_uploaded_by_user_id', 'stored_files', ['uploaded_by_user_id'])

    # 13. application_documents table
    op.create_table(
        'application_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('od_applications.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('stored_file_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stored_files.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('document_type', sa.Enum('ORIGINAL_SIGNED_OD_FORM', 'EVENT_INVITATION', 'PARENT_CONSENT', 'OTHER', name='document_type_enum'), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_application_documents_application_id', 'application_documents', ['application_id'])
    op.create_index('ix_application_documents_stored_file_id', 'application_documents', ['stored_file_id'])

    # 14. evidence_submissions table
    op.create_table(
        'evidence_submissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_day_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('event_days.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('venue_photo_file_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stored_files.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('organizer_proof_file_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('stored_files.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('submission_notes', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(), nullable=False),
        sa.Column('server_received_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_evidence_submissions_event_day_id', 'evidence_submissions', ['event_day_id'])
    op.create_index('ix_evidence_submissions_venue_photo_file_id', 'evidence_submissions', ['venue_photo_file_id'])
    op.create_index('ix_evidence_submissions_organizer_proof_file_id', 'evidence_submissions', ['organizer_proof_file_id'])

    # 15. location_captures table (GPS stored independently from photograph)
    op.create_table(
        'location_captures',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('evidence_submission_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('evidence_submissions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('accuracy_meters', sa.Float(), nullable=True),
        sa.Column('captured_at', sa.DateTime(), nullable=False),
        sa.Column('server_recorded_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('latitude BETWEEN -90 AND 90', name='ck_location_latitude_range'),
        sa.CheckConstraint('longitude BETWEEN -180 AND 180', name='ck_location_longitude_range'),
        sa.CheckConstraint(
            "accuracy_meters >= 0 AND accuracy_meters < 'Infinity'::double precision",
            name='ck_location_accuracy_range',
        ),
    )
    op.create_index('ix_location_captures_evidence_submission_id', 'location_captures', ['evidence_submission_id'])

    # 16. evidence_reviews table
    op.create_table(
        'evidence_reviews',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('evidence_submission_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('evidence_submissions.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('reviewed_by_tutor_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tutor_profiles.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('review_status', sa.Enum('APPROVED', 'REJECTED', 'CORRECTION_REQUIRED', name='evidence_review_status_enum'), nullable=False),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_evidence_reviews_evidence_submission_id', 'evidence_reviews', ['evidence_submission_id'])
    op.create_index('ix_evidence_reviews_reviewed_by_tutor_id', 'evidence_reviews', ['reviewed_by_tutor_id'])

    # 17. application_status_history table
    op.create_table(
        'application_status_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('od_applications.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('from_status', application_status_type, nullable=True),
        sa.Column('to_status', application_status_type, nullable=False),
        sa.Column('changed_by_user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_application_status_history_application_id', 'application_status_history', ['application_id'])
    op.create_index('ix_application_status_history_created_at', 'application_status_history', ['created_at'])

    # 18. notifications table
    op.create_table(
        'notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('notification_type', sa.Enum('APPLICATION_SUBMITTED', 'PRE_APPROVED', 'CORRECTION_REQUESTED', 'FINAL_VERIFIED', 'REJECTED', 'SYSTEM', name='notification_type_enum'), nullable=False),
        sa.Column('is_read', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_is_read', 'notifications', ['is_read'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])

    # 19. refresh_tokens table
    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('is_revoked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'], unique=True)
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'])

    restrict_client_access()


def downgrade() -> None:
    op.execute('SET LOCAL search_path TO public')
    op.drop_table('refresh_tokens')
    op.drop_table('notifications')
    op.drop_table('application_status_history')
    op.drop_table('evidence_reviews')
    op.drop_table('location_captures')
    op.drop_table('evidence_submissions')
    op.drop_table('application_documents')
    op.drop_table('stored_files')
    op.drop_table('event_days')
    op.drop_table('od_applications')
    op.drop_table('class_tutor_assignments')
    op.drop_table('student_class_enrollments')
    op.drop_table('admin_profiles')
    op.drop_table('tutor_profiles')
    op.drop_table('student_profiles')
    op.drop_table('classes')
    op.drop_table('academic_years')
    op.drop_table('departments')
    op.drop_table('users')
    
    op.execute('DROP TYPE IF EXISTS notification_type_enum')
    op.execute('DROP TYPE IF EXISTS evidence_review_status_enum')
    op.execute('DROP TYPE IF EXISTS document_type_enum')
    op.execute('DROP TYPE IF EXISTS event_day_status_enum')
    op.execute('DROP TYPE IF EXISTS day_session_enum')
    op.execute('DROP TYPE IF EXISTS event_category_enum')
    op.execute('DROP TYPE IF EXISTS application_status_enum')
    op.execute('DROP TYPE IF EXISTS user_role_enum')
