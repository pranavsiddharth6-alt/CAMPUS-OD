import asyncio
import json
import sqlite3
import unittest
from base64 import b64decode
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.orm import sessionmaker

from app.api.v1 import od_applications as api
from app.core.access_tokens import create_access_token
from app.core.config import settings
from app.core.passwords import hash_password
from app.database.demo import DemoSession, create_demo_engine, upgrade_demo_hod
from app.local_demo import initialize_demo, prepare_demo_od
from app.main import app
from app.models.academic import ClassTutorAssignment, Department, HODAssignment, StudentClassEnrollment
from app.models.application import ApplicationStatusHistory, ODApplication
from app.models.enums import AccountStatus, UserRole
from app.models.evidence import EvidenceReview, EvidenceSubmission, LocationCapture, StoredFile
from app.models.user import StudentProfile, TutorProfile, User
from app.services.auth_sessions import AuthSessionService
from app.services.demo_accounts import DEMO_ORIGIN, DEMO_STUDENT, DEMO_TUTOR
from app.services.storage import LocalStorageService


class ODWorkflowTests(unittest.IsolatedAsyncioTestCase):
    path = "/api/v1/applications"
    tutor_path = "/api/v1/tutor/applications"
    original = b"%PDF-1.7\r\n% fictional original fixture\r\n%%EOF\r\n"
    supporting = b"%PDF-1.7\n% fictional supporting fixture\n%%EOF\n"
    venue_photo = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l2sAAAAASUVORK5CYII=")

    @classmethod
    def setUpClass(cls):
        cls.password_hash = hash_password("fictional isolated workflow password")

    def setUp(self):
        self.enterContext(patch("pg8000.dbapi.connect", side_effect=AssertionError("PostgreSQL is blocked")))
        self.enterContext(patch("app.core.access_tokens.settings", SimpleNamespace(
            JWT_SIGNING_SECRET=SecretStr("s" * 48), JWT_ISSUER="isolated-od", JWT_AUDIENCE="isolated-test",
            JWT_ALGORITHM="HS256", JWT_ACCESS_TOKEN_MINUTES=10,
        )))
        directory = Path(self.enterContext(TemporaryDirectory())) / "workflow-demo"
        self.directory = directory
        initialize_demo(directory)
        engine = create_demo_engine(directory)
        self.addCleanup(engine.dispose)
        self.factory = sessionmaker(engine, class_=DemoSession, expire_on_commit=False)
        self.storage = LocalStorageService(str(directory / "test-private-storage"))
        self.enterContext(patch.object(api, "storage_service", self.storage))
        self.enterContext(patch.object(api, "get_session_factory", return_value=self.factory))
        self.enterContext(patch("app.dependencies.auth.get_session_factory", return_value=self.factory))
        self.enterContext(patch("app.api.v1.admin_academics.get_session_factory", return_value=self.factory))

        with self.factory.begin() as db:
            student = User(email=DEMO_STUDENT.email, role=UserRole.STUDENT, account_status=AccountStatus.ACTIVE,
                           hashed_password=self.password_hash, student_profile=StudentProfile(
                               full_name=DEMO_STUDENT.full_name, roll_number=DEMO_STUDENT.roll_number,
                               register_number=DEMO_STUDENT.register_number, department_id=DEMO_STUDENT.department_id,
                           ))
            student.student_profile.enrollments.append(StudentClassEnrollment(
                class_id=DEMO_STUDENT.class_id, academic_year_id=DEMO_STUDENT.academic_year_id, is_active=True,
            ))
            tutor = User(email=DEMO_TUTOR.email, role=UserRole.TUTOR, account_status=AccountStatus.ACTIVE,
                         hashed_password=self.password_hash, tutor_profile=TutorProfile(
                             full_name=DEMO_TUTOR.full_name, staff_id=DEMO_TUTOR.staff_id,
                             designation=DEMO_TUTOR.designation, department_id=DEMO_TUTOR.department_id,
                         ))
            other_student = User(email="other.student@example.com", role=UserRole.STUDENT,
                                 account_status=AccountStatus.ACTIVE, hashed_password=self.password_hash)
            other_tutor = User(email="other.tutor@example.com", role=UserRole.TUTOR,
                               account_status=AccountStatus.ACTIVE, hashed_password=self.password_hash,
                               tutor_profile=TutorProfile(full_name="Other Demo Tutor", staff_id="DEMO-T002",
                                                         designation="Fictional Tutor", department_id=DEMO_TUTOR.department_id))
            admin = User(email="other.admin@example.com", role=UserRole.ADMIN,
                         account_status=AccountStatus.ACTIVE, hashed_password=self.password_hash)
            hod = User(email="hod@example.com", role=UserRole.HOD, account_status=AccountStatus.ACTIVE,
                       hashed_password=self.password_hash)
            other_hod = User(email="other.hod@example.com", role=UserRole.HOD, account_status=AccountStatus.ACTIVE,
                             hashed_password=self.password_hash)
            other_department = Department(code="OTHER", name="Other fictional department")
            db.add_all((student, tutor, other_student, other_tutor, admin, hod, other_hod, other_department))
            db.flush()
            db.add_all((
                HODAssignment(department_id=DEMO_STUDENT.department_id, user_id=hod.id,
                              full_name="Demo HOD", assigned_by_user_id=admin.id),
                HODAssignment(department_id=other_department.id, user_id=other_hod.id,
                              full_name="Other HOD", assigned_by_user_id=admin.id),
            ))

        prepare_demo_od(directory)
        prepare_demo_od(directory)
        sessions = AuthSessionService(session_factory=self.factory, session_lifetime=timedelta(hours=1),
                                      refresh_lifetime=timedelta(hours=1))

        def bearer(user):
            session = sessions.create_session(user.id)
            return {"Authorization": f"Bearer {create_access_token(user.id, session.session_id)}"}

        self.student, self.tutor, self.other_student, self.other_tutor = map(bearer, (student, tutor, other_student, other_tutor))
        self.admin = bearer(admin) | {"Origin": DEMO_ORIGIN, "X-CSRF-Protection": "1"}
        self.hod, self.other_hod = map(bearer, (hod, other_hod))
        self.tutor_id = tutor.id
        self.other_tutor_profile = other_tutor.tutor_profile.id
        self.details = {
            "event_name": "Fictional university quiz", "event_category": "ACADEMIC",
            "host_institution": "Demo Host", "venue_location": "Demo Auditorium",
            "event_days": [{"event_date": "2026-11-22"}, {"event_date": "2026-11-20", "session": "FORENOON"}],
            "description": "Representing the fictional class.",
        }

    async def asyncSetUp(self):
        self.client = await self.enterAsyncContext(AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost"))

    async def post(self, *, headers=None, details=None, files=None, path=None):
        parts = [("details", (None, json.dumps(self.details if details is None else details)))]
        if files is None:
            files = [("original_form", ("signed original.pdf", self.original, "application/pdf"))]
        return await self.client.post(path or self.path, headers=self.student if headers is None else headers,
                                      files=parts + files)

    async def decision(self, application, action, *, headers=None, remarks="Fictional tutor remarks"):
        return await self.client.post(f"{self.tutor_path}/{application['id']}/decision",
                                      headers=self.tutor if headers is None else headers,
                                      json={"action": action, "remarks": remarks, "expected_revision": application["revision"]})

    async def create(self):
        response = await self.post(files=[
            ("original_form", ("signed original.pdf", self.original, "application/pdf")),
            ("event_invitation", ("invitation.pdf", self.supporting, "application/pdf")),
        ])
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def assert_empty(self):
        with self.factory() as db:
            self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(ODApplication)), 0)
            self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(StoredFile)), 0)
        self.assertEqual(list(Path(self.storage.base_dir).iterdir()), [])

    async def test_submission_correction_resubmission_preapproval_and_original_bytes(self):
        initial = await self.create()
        location = f"{self.path}/{initial['id']}"
        self.assertEqual((initial["tutor_name"], initial["start_date"], initial["end_date"], initial["total_days"]),
                         (DEMO_TUTOR.full_name, "2026-11-20", "2026-11-22", 2))
        self.assertEqual(initial["event_days"][0]["session"], "FORENOON")
        self.assertEqual(initial["status"], "SUBMITTED")
        documents = {item["document_type"]: item for item in initial["documents"]}
        self.assertEqual(set(documents), {"ORIGINAL_SIGNED_OD_FORM", "EVENT_INVITATION"})
        original = documents["ORIGINAL_SIGNED_OD_FORM"]
        self.assertEqual(set(original), {"id", "document_type", "filename"})
        download = f"{location}/documents/{original['id']}"
        for headers in (self.student, self.tutor):
            result = await self.client.get(download, headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.content, self.original)
            self.assertTrue(result.headers["content-disposition"].startswith("attachment;"))
            self.assertEqual(result.headers["x-content-type-options"], "nosniff")
        listed = (await self.client.get(self.tutor_path, headers=self.tutor)).json()
        self.assertEqual([item["id"] for item in listed], [initial["id"]])

        correction = (await self.decision(initial, "REQUEST_CORRECTION", remarks="Clarify the event venue.")).json()
        self.assertEqual(correction["status"], "CORRECTION_REQUESTED")
        self.assertEqual(correction["history"][-1]["remarks"], "Clarify the event venue.")
        revised = self.details | {
            "venue_location": "Corrected Fictional Hall", "expected_revision": correction["revision"],
            "event_days": [{"event_date": "2026-11-22"}, {"event_date": "2026-11-24"}],
        }
        rejected_replacement = await self.post(details=revised, path=f"{location}/resubmit")
        self.assertEqual(rejected_replacement.status_code, 422)
        resubmitted = await self.post(details=revised, path=f"{location}/resubmit",
                                      files=[("parent_consent", ("consent.pdf", self.supporting, "application/pdf"))])
        self.assertEqual(resubmitted.status_code, 200, resubmitted.text)
        second = resubmitted.json()
        self.assertEqual(second["status"], "SUBMITTED")
        self.assertEqual([day["event_date"] for day in second["event_days"]], ["2026-11-22", "2026-11-24"])
        self.assertEqual(len(second["documents"]), 3)
        self.assertEqual((await self.decision(initial, "PREAPPROVE")).status_code, 409)
        self.assertEqual((await self.decision(second, "PREAPPROVE")).status_code, 200)
        student_view = (await self.client.get(location, headers=self.student)).json()
        self.assertEqual(student_view["status"], "PRE_APPROVED")
        self.assertEqual(student_view["venue_location"], "Corrected Fictional Hall")
        self.assertEqual([entry["to_status"] for entry in student_view["history"]],
                         ["SUBMITTED", "CORRECTION_REQUESTED", "SUBMITTED", "PRE_APPROVED"])
        self.assertEqual((await self.client.get(download, headers=self.student)).content, self.original)
        self.assertEqual((await self.client.get(self.path, headers=self.student)).json()[0]["status"], "PRE_APPROVED")

    async def test_role_and_object_scope_apply_to_reads_downloads_and_writes(self):
        application = await self.create()
        path = f"{self.path}/{application['id']}"
        document = application["documents"][0]["id"]
        for credentials in (self.other_student, self.other_tutor):
            self.assertEqual((await self.client.get(path, headers=credentials)).status_code, 404)
            self.assertEqual((await self.client.get(f"{path}/documents/{document}", headers=credentials)).status_code, 404)
        self.assertEqual((await self.client.get(self.path, headers=self.other_student)).json(), [])
        self.assertEqual((await self.client.get(self.tutor_path, headers=self.other_tutor)).json(), [])
        self.assertEqual((await self.client.get(self.path)).status_code, 401)
        self.assertEqual((await self.post(headers=self.tutor)).status_code, 403)
        self.assertEqual((await self.decision(application, "REJECT", headers=self.student)).status_code, 403)
        self.assertEqual((await self.decision(application, "REJECT", headers=self.other_tutor)).status_code, 404)
        self.assertEqual((await self.post(headers=self.other_student, path=f"{path}/resubmit",
                                          details=self.details | {"expected_revision": application["revision"]}, files=[]))
                         .status_code, 404)

    async def test_reject_is_terminal_and_competing_decisions_do_not_both_commit(self):
        application = await self.create()
        missing = await self.decision(application, "REJECT", remarks=" ")
        self.assertEqual(missing.status_code, 422)
        actions = await asyncio.gather(self.decision(application, "REJECT"), self.decision(application, "REJECT"))
        self.assertEqual(sorted(action.status_code for action in actions), [200, 409])
        detail = (await self.client.get(f"{self.path}/{application['id']}", headers=self.student)).json()
        self.assertEqual(detail["status"], "REJECTED")
        self.assertEqual(len(detail["history"]), 2)
        self.assertEqual((await self.decision(detail, "PREAPPROVE")).status_code, 409)

    async def test_rejects_invalid_inputs_size_and_spoofed_file_types(self):
        self.assertEqual((await self.post(details=self.details | {"assigned_tutor_id": str(self.tutor_id)})).status_code, 422)
        self.assertEqual((await self.post(details=self.details | {"event_days": [self.details["event_days"][0]] * 2})).status_code, 422)
        self.assertEqual((await self.post(files=[])).status_code, 422)
        self.assertEqual((await self.post(files=[("original_form", ("doc.pdf", b"fake", "application/pdf"))])).status_code, 415)
        self.assertEqual((await self.post(files=[("original_form", ("doc.pdf", self.original, "image/png"))])).status_code, 415)
        self.assertEqual((await self.post(files=[("original_form", ("../doc.pdf", self.original, "application/pdf"))])).status_code, 422)
        with patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", len(self.original) - 1):
            self.assertEqual((await self.post()).status_code, 413)
        self.assert_empty()

    async def test_missing_enrollment_inactive_assignment_and_inactive_tutor_are_rejected(self):
        self.assertEqual((await self.post(headers=self.other_student)).status_code, 409)
        with self.factory.begin() as db:
            db.execute(sa.update(ClassTutorAssignment).values(is_active=False))
        self.assertEqual((await self.post()).status_code, 409)
        with self.factory.begin() as db:
            db.execute(sa.update(ClassTutorAssignment).values(is_active=True))
            db.get(User, self.tutor_id).account_status = AccountStatus.DISABLED
        self.assertEqual((await self.post()).status_code, 409)
        self.assert_empty()

    async def test_partial_storage_failure_rolls_back_and_cleans_saved_files(self):
        save = self.storage.save_file

        def fail_second(content, *args):
            if content == self.supporting:
                raise OSError("synthetic storage failure")
            return save(content, *args)

        with patch.object(self.storage, "save_file", side_effect=fail_second):
            result = await self.post(files=[
                ("original_form", ("first.pdf", self.original, "application/pdf")),
                ("event_invitation", ("second.pdf", self.supporting, "application/pdf")),
            ])
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json(), {"detail": "The OD service is temporarily unavailable."})
        self.assert_empty()

    async def test_download_rejects_storage_bytes_that_fail_the_saved_checksum(self):
        application = await self.create()
        with self.factory() as db:
            key = db.scalar(sa.select(StoredFile.storage_key).where(StoredFile.original_filename == "signed original.pdf"))
        (Path(self.storage.base_dir) / key).write_bytes(b"x" * len(self.original))
        original = next(doc for doc in application["documents"] if doc["document_type"] == "ORIGINAL_SIGNED_OD_FORM")
        response = await self.client.get(
            f"{self.path}/{application['id']}/documents/{original['id']}", headers=self.student,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "The stored document failed its integrity check."})

    async def preapproved_days(self):
        application = await self.create()
        self.assertEqual((await self.decision(application, "PREAPPROVE")).status_code, 200)
        data = (await self.client.get(f"{self.path}/{application['id']}/evidence", headers=self.student)).json()
        return application, data["days"]

    async def evidence(self, application, day, *, gps=None, files=None, headers=None):
        details = {
            "gps": {
                "latitude": 11.125, "longitude": 77.25, "accuracy_meters": 275.5,
                "captured_at": "2026-11-01T15:30:00+05:30",
            } if gps is None else gps,
            "submitted_at": "2026-11-23T10:00:00Z", "notes": "Fictional participation evidence.",
        }
        if files is None:
            files = [("venue_photo", ("venue.png", self.venue_photo, "image/png")),
                     ("organizer_proof", ("organizer.pdf", self.supporting, "application/pdf"))]
        return await self.client.post(f"{self.path}/{application['id']}/days/{day['id']}/evidence",
                                      headers=headers or self.student,
                                      files=[("details", (None, json.dumps(details)))] + files)

    async def review_day(self, application, day, attempt, status, *, headers=None, remarks="Fictional evidence remarks."):
        return await self.client.post(
            f"{self.tutor_path}/{application['id']}/days/{day['id']}/evidence/{attempt['id']}/review",
            headers=headers or self.tutor, json={"review_status": status, "remarks": remarks},
        )

    @staticmethod
    def attempt(response, index=0):
        return response.json()["days"][index]["attempts"][-1]

    async def hod_decision(self, application, action, *, remarks="", headers=None):
        return await self.client.post(f"/api/v1/hod/applications/{application['id']}/decision",
                                      headers=self.hod if headers is None else headers,
                                      json={"action": action, "remarks": remarks, "expected_revision": application["revision"]})

    async def pending_hod(self):
        application, days = await self.preapproved_days()
        for index, day in enumerate(days):
            attempt = self.attempt(await self.evidence(application, day), index)
            result = await self.review_day(application, day, attempt, "APPROVED")
            self.assertEqual(result.status_code, 200, result.text)
        url = f"{self.path}/{application['id']}"
        detail = await self.client.get(url, headers=self.hod)
        self.assertEqual(detail.status_code, 200, detail.text)
        return detail.json(), result.json()["days"]

    async def test_multi_day_evidence_correction_and_verified_finalization(self):
        application, (first, second) = await self.preapproved_days()
        self.assertEqual((await self.client.get(f"{self.path}/{application['id']}", headers=self.hod)).status_code, 404)
        first_response = await self.evidence(application, first)
        self.assertEqual(first_response.status_code, 201, first_response.text)
        first_attempt = self.attempt(first_response)
        self.assertEqual(first_attempt["gps"], {
            "latitude": 11.125, "longitude": 77.25, "accuracy_meters": 275.5,
            "captured_at": "2026-11-01T10:00:00Z",
        })
        for kind, content in (("venue-photo", self.venue_photo), ("organizer-proof", self.supporting)):
            endpoint = f"{self.path}/{application['id']}/evidence/{first_attempt['id']}/files/{kind}"
            for headers in (self.student, self.tutor):
                result = await self.client.get(endpoint, headers=headers)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.content, content)
                self.assertEqual(result.headers["x-content-type-options"], "nosniff")
        self.assertEqual((await self.evidence(application, first)).status_code, 409)
        second_upload = await self.evidence(application, second)
        self.assertEqual(second_upload.status_code, 201)
        second_attempt = self.attempt(second_upload, 1)
        correction = await self.review_day(application, first, first_attempt, "CORRECTION_REQUIRED", remarks="Clarify the venue.")
        self.assertEqual(correction.status_code, 200)
        self.assertEqual(correction.json()["days"][0]["state"], "CORRECTION_REQUIRED")
        self.assertEqual(self.attempt(correction)["reviews"][0]["remarks"], "Clarify the venue.")
        partial = await self.review_day(application, second, second_attempt, "APPROVED")
        self.assertEqual(partial.json()["status"], "AWAITING_PARTICIPATION_PROOF")
        self.assertEqual(partial.json()["days"][1]["state"], "VERIFIED")
        resubmission = await self.evidence(application, first)
        self.assertEqual(resubmission.status_code, 201)
        newest = self.attempt(resubmission)
        self.assertNotEqual(first_attempt["id"], newest["id"])
        self.assertEqual(len(resubmission.json()["days"][0]["attempts"]), 2)
        self.assertEqual((await self.review_day(application, first, first_attempt, "APPROVED")).status_code, 409)
        concurrent = await asyncio.gather(
            self.review_day(application, first, newest, "APPROVED"),
            self.review_day(application, first, newest, "APPROVED"),
        )
        self.assertEqual(sorted(response.status_code for response in concurrent), [200, 409])
        verified = next(response.json() for response in concurrent if response.status_code == 200)
        self.assertEqual(verified["status"], "UNDER_HOD_REVIEW")
        self.assertEqual([day["state"] for day in verified["days"]], ["VERIFIED", "VERIFIED"])
        self.assertEqual((await self.evidence(application, first)).status_code, 409)
        details = (await self.client.get(f"{self.path}/{application['id']}", headers=self.student)).json()
        self.assertEqual(details["history"][-1]["to_status"], "UNDER_HOD_REVIEW")
        self.assertEqual((await self.hod_decision(details, "APPROVE", headers=self.tutor)).status_code, 403)
        self.assertEqual((await self.hod_decision(details, "APPROVE", headers=self.student)).status_code, 403)
        self.assertEqual((await self.hod_decision(details, "APPROVE", headers=self.other_hod)).status_code, 404)
        decisions = await asyncio.gather(self.hod_decision(details, "APPROVE"),
                                         self.hod_decision(details, "APPROVE"))
        self.assertEqual(sorted(response.status_code for response in decisions), [200, 409])
        finalized = (await self.client.get(f"{self.path}/{application['id']}", headers=self.student)).json()
        self.assertEqual(finalized["status"], "OD_FINALIZED")
        self.assertEqual(finalized["history"][-1]["hod_name"], "Demo HOD")
        self.assertEqual(sum(entry["to_status"] == "OD_FINALIZED" for entry in finalized["history"]), 1)
        original = next(doc for doc in details["documents"] if doc["document_type"] == "ORIGINAL_SIGNED_OD_FORM")
        for headers in (self.student, self.tutor, self.hod):
            result = await self.client.get(f"{self.path}/{application['id']}/documents/{original['id']}", headers=headers)
            self.assertEqual(result.content, self.original)
        with self.factory() as db:
            for model in (EvidenceSubmission, LocationCapture, EvidenceReview):
                self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(model)), 3)

    async def test_additive_upgrade_preserves_legacy_finalization_and_private_files_after_restart(self):
        application = await self.create()
        with self.factory.begin() as db:
            row = db.get(ODApplication, UUID(application["id"]))
            row.status = "OD_FINALIZED"
            row.status_history.append(ApplicationStatusHistory(
                from_status="UNDER_FINAL_VERIFICATION", to_status="OD_FINALIZED",
                changed_by_user_id=self.tutor_id, remarks="Legacy tutor finalization.",
            ))
        before = (await self.client.get(f"{self.path}/{application['id']}", headers=self.student)).json()
        # Recreate the two tables with their original columns and constraints in this fixture.
        with closing(sqlite3.connect(self.directory / "campus_od.sqlite3")) as legacy, legacy:
            legacy.execute("BEGIN")
            for table, field in (("application_status_history", "hod_assignment_id"),
                                 ("od_applications", "department_id")):
                schema, = legacy.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()
                lines = [line for line in schema.splitlines() if field not in line]
                lines[-2] = lines[-2].rstrip().removesuffix(",")
                definition = "\n".join(lines).replace(f"CREATE TABLE {table}", "CREATE TABLE legacy_table", 1)
                columns = ", ".join(row[1] for row in legacy.execute(f"PRAGMA table_info({table})") if row[1] != field)
                indexes = [sql for sql, in legacy.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ?", (table,)
                ) if sql and field not in sql]
                legacy.execute(definition)
                legacy.execute(f"INSERT INTO legacy_table ({columns}) SELECT {columns} FROM {table}")
                legacy.execute(f"DROP TABLE {table}")
                legacy.execute(f"ALTER TABLE legacy_table RENAME TO {table}")
                for index in indexes:
                    legacy.execute(index)
            legacy.execute("DROP TABLE hod_assignments")
            legacy.execute("DROP TRIGGER users_revoke_changed_identity_sessions")
        restarted = create_demo_engine(self.directory)
        self.addCleanup(restarted.dispose)
        upgrade_demo_hod(restarted)
        upgrade_demo_hod(restarted)
        with restarted.connect() as db:
            self.assertEqual(db.exec_driver_sql("PRAGMA foreign_key_check").fetchall(), [])
            self.assertIsNotNone(db.exec_driver_sql("SELECT department_id FROM od_applications").scalar_one())
        factory = sessionmaker(restarted, class_=DemoSession, expire_on_commit=False)
        with patch.object(api, "get_session_factory", return_value=factory), patch(
            "app.dependencies.auth.get_session_factory", return_value=factory,
        ):
            base = f"{self.path}/{application['id']}"
            response = await self.client.get(base, headers=self.student)
            self.assertEqual(response.json(), before)
            self.assertEqual(response.json()["status"], "OD_FINALIZED")
            self.assertIsNone(response.json()["history"][-1]["hod_name"])
            original = await self.client.get(base + f"/documents/{before['documents'][0]['id']}", headers=self.student)
            self.assertEqual(original.content, self.original)
            self.assertEqual((await self.client.get("/api/v1/hod/applications", headers=self.hod)).json(), [])

    async def test_hod_scoped_reads_and_rejection(self):
        application, days = await self.pending_hod()
        base = f"{self.path}/{application['id']}"
        attempt_id = days[0]["attempts"][-1]["id"]
        for suffix in ("", "/evidence", f"/documents/{application['documents'][0]['id']}",
                       f"/evidence/{attempt_id}/files/venue-photo"):
            for headers, expected in ((self.hod, 200), (self.other_hod, 404)):
                response = await self.client.get(base + suffix, headers=headers)
                self.assertEqual(response.status_code, expected, response.text)
        response = await self.client.get(base + f"/evidence/{attempt_id}/files/organizer-proof", headers=self.hod)
        self.assertEqual(response.content, self.supporting)
        response = await self.client.get(base + "/evidence", headers=self.hod)
        self.assertIn("gps", response.json()["days"][0]["attempts"][0])
        self.assertEqual((await self.client.post(base + "/resubmit", headers=self.hod)).status_code, 403)
        self.assertEqual((await self.evidence(application, days[0], headers=self.hod)).status_code, 403)
        self.assertEqual((await self.decision(application, "PREAPPROVE", headers=self.hod)).status_code, 403)
        self.assertEqual((await self.review_day(application, days[0], {"id": attempt_id}, "APPROVED",
                                                headers=self.hod)).status_code, 403)
        self.assertEqual((await self.client.get("/api/v1/hod/applications", headers=self.student)).status_code, 403)
        self.assertEqual((await self.client.get("/api/v1/hod/applications", headers=self.other_hod)).json(), [])
        queue = await self.client.get("/api/v1/hod/applications?view=pending", headers=self.hod)
        self.assertEqual([item["id"] for item in queue.json()], [application["id"]])
        self.assertEqual((await self.hod_decision(application, "REJECT")).status_code, 422)
        rejected = await self.hod_decision(application, "REJECT", remarks="The organizer did not confirm.")
        self.assertEqual(rejected.status_code, 200, rejected.text)
        self.assertEqual(rejected.json()["status"], "REJECTED")
        self.assertEqual(rejected.json()["history"][-1]["remarks"], "The organizer did not confirm.")
        self.assertEqual((await self.hod_decision(application, "APPROVE")).status_code, 409)
        history = await self.client.get("/api/v1/hod/applications?view=history", headers=self.hod)
        self.assertEqual([item["id"] for item in history.json()], [application["id"]])
        counts = await self.client.get("/api/v1/hod/dashboard", headers=self.hod)
        self.assertEqual(counts.json(), {"pending": 0, "approved": 0, "rejected": 1})

    async def test_hod_correction_requires_tutor_rereview_and_preserves_evidence(self):
        application, days = await self.pending_hod()
        base = f"{self.path}/{application['id']}"
        requested = await self.hod_decision(application, "REQUEST_CORRECTION", remarks="Clarify participation.")
        self.assertEqual(requested.status_code, 200, requested.text)
        self.assertEqual(requested.json()["status"], "HOD_CORRECTION_REQUESTED")
        corrections = self.details | {"description": "Updated participation notes.",
                                      "expected_revision": requested.json()["revision"]}
        changed_venue = await self.post(details=corrections | {"venue_location": "A different venue"},
                                        files=[], path=base + "/resubmit")
        self.assertEqual(changed_venue.status_code, 422)
        resubmitted = await self.post(details=corrections, files=[], path=base + "/resubmit")
        self.assertEqual(resubmitted.status_code, 200, resubmitted.text)
        correction = resubmitted.json()
        self.assertEqual(correction["status"], "UNDER_TUTOR_CORRECTION_REVIEW")
        self.assertEqual((await self.hod_decision(correction, "APPROVE")).status_code, 409)
        first_attempt = days[0]["attempts"][0]
        reopen = await self.review_day(application, days[0], first_attempt, "CORRECTION_REQUIRED")
        self.assertEqual(reopen.status_code, 200, reopen.text)
        self.assertEqual((await self.decision(correction, "PREAPPROVE")).status_code, 409)
        self.assertEqual(reopen.json()["days"][1]["state"], "VERIFIED")
        replaced = await self.evidence(application, days[0])
        self.assertEqual(replaced.status_code, 201, replaced.text)
        verified = await self.review_day(application, days[0], self.attempt(replaced), "APPROVED")
        self.assertEqual(verified.json()["status"], "UNDER_TUTOR_CORRECTION_REVIEW")
        self.assertEqual(len(verified.json()["days"][0]["attempts"]), 2)
        self.assertEqual(len(verified.json()["days"][0]["attempts"][0]["reviews"]), 2)
        forwarded = await self.decision(correction, "PREAPPROVE")
        self.assertEqual(forwarded.status_code, 200, forwarded.text)
        self.assertEqual(forwarded.json()["status"], "UNDER_HOD_REVIEW")
        self.assertEqual((await self.hod_decision(application, "APPROVE")).status_code, 409)
        self.assertEqual((await self.hod_decision(forwarded.json(), "APPROVE")).status_code, 200)

    async def test_evidence_requires_preapproval_both_files_and_valid_gps(self):
        application = await self.create()
        state = (await self.client.get(f"{self.path}/{application['id']}/evidence", headers=self.student)).json()
        first = state["days"][0]
        self.assertEqual((await self.evidence(application, first)).status_code, 409)
        self.assertEqual((await self.decision(application, "PREAPPROVE")).status_code, 200)
        self.assertEqual((await self.evidence(application, first, gps={})).status_code, 422)
        gps = {"latitude": 11, "longitude": 77, "accuracy_meters": 100, "captured_at": "2026-11-22T10:00:00Z"}
        for invalid in ({"latitude": 91}, {"latitude": True}, {"longitude": -181}, {"accuracy_meters": -1},
                        {"captured_at": "2026-11-22T10:00:00"}):
            self.assertEqual((await self.evidence(application, first, gps=gps | invalid)).status_code, 422)
        missing = [("venue_photo", ("venue.png", self.venue_photo, "image/png"))]
        self.assertEqual((await self.evidence(application, first, files=missing)).status_code, 422)
        wrong_format = [("venue_photo", ("venue.pdf", self.original, "application/pdf")),
                        ("organizer_proof", ("organizer.pdf", self.supporting, "application/pdf"))]
        self.assertEqual((await self.evidence(application, first, files=wrong_format)).status_code, 415)
        with patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", len(self.venue_photo) - 1):
            self.assertEqual((await self.evidence(application, first)).status_code, 413)
        with self.factory() as db:
            self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(EvidenceSubmission)), 0)

    async def test_day_rejection_does_not_stop_independent_review_or_finalize_application(self):
        application, (first, second) = await self.preapproved_days()
        first_attempt = self.attempt(await self.evidence(application, first))
        rejected = await self.review_day(application, first, first_attempt, "REJECTED")
        self.assertEqual(rejected.json()["days"][0]["state"], "REJECTED")
        self.assertEqual((await self.evidence(application, first)).status_code, 409)
        second_attempt = self.attempt(await self.evidence(application, second), 1)
        final = await self.review_day(application, second, second_attempt, "APPROVED")
        self.assertEqual(final.json()["status"], "REJECTED")
        self.assertEqual([day["state"] for day in final.json()["days"]], ["REJECTED", "VERIFIED"])

    async def test_evidence_and_original_downloads_stay_scoped(self):
        application, (first, second) = await self.preapproved_days()
        attempt = self.attempt(await self.evidence(application, first))
        evidence_url = f"{self.path}/{application['id']}/evidence"
        original = next(doc for doc in application["documents"] if doc["document_type"] == "ORIGINAL_SIGNED_OD_FORM")
        for headers in (self.other_student, self.other_tutor):
            for url in (evidence_url, f"{evidence_url}/{attempt['id']}/files/venue-photo",
                        f"{self.path}/{application['id']}/documents/{original['id']}"):
                self.assertEqual((await self.client.get(url, headers=headers)).status_code, 404)
        self.assertEqual((await self.client.get(evidence_url)).status_code, 401)
        self.assertEqual((await self.evidence(application, first, headers=self.other_student)).status_code, 404)
        self.assertEqual((await self.evidence(application, first, headers=self.tutor)).status_code, 403)
        self.assertEqual((await self.review_day(application, first, attempt, "APPROVED", headers=self.other_tutor)).status_code, 404)
        self.assertEqual((await self.review_day(application, first, attempt, "APPROVED", headers=self.student)).status_code, 403)
        self.assertEqual((await self.review_day(application, second, attempt, "APPROVED")).status_code, 404)
        self.assertEqual((await self.review_day(application, first, attempt, "APPROVED", remarks=" ")).status_code, 422)

    async def test_demo_academic_mappings_require_admin_and_apply_to_future_applications(self):
        existing = await self.create()
        admin_path = "/api/v1/admin/academics"
        mapping = f"{admin_path}/classes/{DEMO_STUDENT.class_id}/tutor"
        with patch.multiple(settings, ENVIRONMENT="local-demo", LOCAL_DEMO_DIR=self.directory, CORS_ORIGINS=[DEMO_ORIGIN]):
            self.assertEqual((await self.client.get(admin_path, headers=self.tutor)).status_code, 403)
            self.assertEqual((await self.client.put(mapping, headers=self.student, json={"tutor_id": None})).status_code, 403)
            info = await self.client.get(admin_path, headers=self.admin)
            self.assertEqual(info.status_code, 200)
            record, = info.json()["classes"]
            self.assertEqual(record["assignment"]["tutor_name"], DEMO_TUTOR.full_name)
            self.assertEqual(record["students"][0]["roll_number"], DEMO_STUDENT.roll_number)
            self.assertEqual((await self.client.put(mapping, headers=self.admin, json={"tutor_id": str(uuid4())})).status_code, 409)
            self.assertEqual((await self.client.put(mapping, headers=self.admin, json={"tutor_id": None})).status_code, 204)
            self.assertEqual((await self.post()).status_code, 409)
            changed = await self.client.put(mapping, headers=self.admin, json={"tutor_id": str(self.other_tutor_profile)})
            self.assertEqual(changed.status_code, 204)
        future = await self.create()
        self.assertEqual(future["tutor_name"], "Other Demo Tutor")
        old_view = await self.client.get(f"{self.path}/{existing['id']}", headers=self.tutor)
        self.assertEqual(old_view.json()["tutor_name"], DEMO_TUTOR.full_name)
        self.assertEqual((await self.client.get(admin_path, headers=self.admin)).status_code, 404)
