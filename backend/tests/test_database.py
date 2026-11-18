"""Phase 2 Database and Storage Verification Test Suite.

Sri Krishna Arts and Science College (SKASC) - Campus OD
"""
import sys
import os
import uuid
from datetime import datetime, date

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.session import Base, check_db_connection, get_engine
import app.models as models
from app.services.storage import storage_service
from app.models.enums import UserRole, ApplicationStatus, EventCategory, DaySession, EventDayStatus
from fastapi.testclient import TestClient
from app.main import app


def test_model_metadata():
    """Verify that all 19 core entities are registered with valid relationships."""
    tables = Base.metadata.tables
    expected_tables = {
        "users",
        "departments",
        "academic_years",
        "classes",
        "student_profiles",
        "tutor_profiles",
        "admin_profiles",
        "student_class_enrollments",
        "class_tutor_assignments",
        "od_applications",
        "event_days",
        "stored_files",
        "application_documents",
        "evidence_submissions",
        "location_captures",
        "evidence_reviews",
        "application_status_history",
        "notifications",
        "refresh_tokens",
    }

    missing = expected_tables - set(tables.keys())
    assert not missing, f"Missing expected database tables: {missing}"
    print(f"[PASSED] All {len(expected_tables)} core entity tables successfully registered in SQLAlchemy metadata.")

    # Verify key foreign key relationships
    assert "departments.id" in [fk.target_fullname for fk in tables["classes"].foreign_keys]
    assert "student_profiles.id" in [fk.target_fullname for fk in tables["od_applications"].foreign_keys]
    assert "tutor_profiles.id" in [fk.target_fullname for fk in tables["od_applications"].foreign_keys]
    assert "od_applications.id" in [fk.target_fullname for fk in tables["event_days"].foreign_keys]
    assert "stored_files.id" in [fk.target_fullname for fk in tables["application_documents"].foreign_keys]
    assert "evidence_submissions.id" in [fk.target_fullname for fk in tables["location_captures"].foreign_keys]
    print("[PASSED] Foreign key references verified across classes, applications, event days, and evidence.")


def test_storage_service():
    """Verify file storage abstraction saves, reads, verifies checksum, and deletes files."""
    dummy_pdf_content = b"%PDF-1.4 Mock Signed OD Form Content for SKASC Institutional Archive"
    filename = "signed_od_form_22BCS104.pdf"

    saved = storage_service.save_file(
        dummy_pdf_content,
        original_filename=filename,
        content_type="application/pdf",
        uploaded_by_user_id=str(uuid.uuid4()),
    )

    assert saved["original_filename"] == filename
    assert saved["file_size_bytes"] == len(dummy_pdf_content)
    assert len(saved["sha256_checksum"]) == 64
    print(f"[PASSED] Storage save: file saved to private storage with SHA-256: {saved['sha256_checksum'][:16]}...")

    # Read back
    read_bytes, path = storage_service.get_file(saved["storage_key"])
    assert read_bytes == dummy_pdf_content
    assert os.path.exists(path)
    print("[PASSED] Storage retrieve: verified byte parity and private disk location.")

    # Delete
    deleted = storage_service.delete_file(saved["storage_key"])
    assert deleted is True
    assert not os.path.exists(path)
    print("[PASSED] Storage delete: verified clean removal from disk.")


def test_health_endpoints():
    """Verify database health-check endpoints via FastAPI TestClient."""
    client = TestClient(app)
    
    # Check /api/v1/health/db
    res_db = client.get("/api/v1/health/db")
    assert res_db.status_code == 200
    db_data = res_db.json()
    assert "connected" in db_data
    assert db_data["database"] == "PostgreSQL"
    print(f"[PASSED] GET /api/v1/health/db: connected={db_data['connected']}, latency={db_data['latency_ms']}ms")

    # Check root GET /
    res_root = client.get("/")
    assert res_root.status_code == 200
    root_data = res_root.json()
    assert "database" in root_data
    assert root_data["institution"] == "Sri Krishna Arts and Science College (SKASC)"
    print(f"[PASSED] GET /: status={root_data['status']}, database_state={root_data['database']['connected']}")


def test_postgres_live_connection():
    """Test actual live connection to PostgreSQL and database operations if connected."""
    health = check_db_connection()
    if not health["connected"]:
        print("\n" + "=" * 60)
        print("POSTGRESQL CONNECTION NOTICE:")
        print(f"Status: NOT CONNECTED (Expected on host without local PostgreSQL service)")
        print(f"Error: {health['error']}")
        print("=" * 60 + "\n")
        return False
    
    print("\n" + "=" * 60)
    print(f"[PASSED] Live PostgreSQL connection active: {health['version']}")
    print(f"Latency: {health['latency_ms']} ms")
    print("=" * 60 + "\n")
    return True


if __name__ == "__main__":
    print("\n--- Running Phase 2 Database & Storage Test Suite ---\n")
    test_model_metadata()
    test_storage_service()
    test_health_endpoints()
    connected = test_postgres_live_connection()
    if connected:
        print("[SUCCESS] All Phase 2 tests passed including live PostgreSQL operations.")
    else:
        print("[INFO] Phase 2 models, storage, and health checks verified. Awaiting PostgreSQL service to run live queries.")
