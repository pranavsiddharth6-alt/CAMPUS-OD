import asyncio
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1 import auth
from app.core.config import settings
from app.database import session
from app.database.demo import create_demo_engine, upgrade_demo_admin
from app.local_demo import bootstrap_demo_admin, initialize_demo
from app.main import app
from app.models.enums import AccountActionPurpose, AccountStatus
from app.models.user import AccountActionToken, StudentProfile, User
from app.services.demo_accounts import DEMO_ADMIN_EMAIL, DEMO_ORIGIN, DEMO_STUDENT, DemoInvitationOutbox


class LocalDemoAuthTests(unittest.IsolatedAsyncioTestCase):
    password = "fictional demo fixture password"
    headers = {"Origin": DEMO_ORIGIN, "X-CSRF-Protection": "1"}

    def setUp(self):
        self.enterContext(patch(
            "pg8000.dbapi.connect", side_effect=AssertionError("Live databases are blocked in demo tests"),
        ))
        self.directory = Path(self.enterContext(TemporaryDirectory())) / "isolated-demo"
        initialize_demo(self.directory)
        self.enterContext(patch.multiple(settings, ENVIRONMENT="local-demo", LOCAL_DEMO_DIR=self.directory,
                                         CORS_ORIGINS=[DEMO_ORIGIN]))
        self.enterContext(patch("app.core.access_tokens.settings", SimpleNamespace(
            JWT_SIGNING_SECRET=SecretStr((self.directory / "jwt.key").read_text(encoding="ascii")),
            JWT_ISSUER="isolated-campus-demo", JWT_AUDIENCE="isolated-test", JWT_ALGORITHM="HS256",
            JWT_ACCESS_TOKEN_MINUTES=10,
        )))
        self.enterContext(patch.multiple(session, _engine=None, _SessionLocal=None))
        self.enterContext(patch.object(auth, "_rate_limit", auth._LoginRateLimit()))
        self.enterContext(patch.object(auth, "_activation_rate_limit", auth._LoginRateLimit()))
        self.factory = session.get_session_factory()
        self.addCleanup(session.get_engine().dispose)
        with self.factory() as db:
            self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(User)), 0)
        bootstrap_demo_admin(self.directory, self.password)

    async def asyncSetUp(self):
        self.client = await self.enterAsyncContext(
            AsyncClient(transport=ASGITransport(app=app), base_url="https://localhost"),
        )

    async def login(self, email):
        return await self.client.post("/api/v1/auth/login", headers=self.headers,
                                      json={"email": email, "password": self.password})

    def bearer(self, response):
        self.assertEqual(response.status_code, 200)
        return {**self.headers, "Authorization": f"Bearer {response.json()['access_token']}"}

    async def issue(self, group="students"):
        headers = self.bearer(await self.login(DEMO_ADMIN_EMAIL))
        roster = await self.client.get("/api/v1/admin/demo-roster", headers=headers)
        self.assertEqual(roster.status_code, 200)
        record, = roster.json()[group]
        issued = await self.client.post(f"/api/v1/admin/{group}", headers=headers, json=record)
        self.assertEqual(issued.status_code, 201)
        body = issued.json()
        self.assertEqual(set(body), {"user_id", "profile_id", "invitation_id", "invitation_delivered"})
        self.assertTrue(body["invitation_delivered"])
        invitation_id = UUID(body["invitation_id"])
        invitation = DemoInvitationOutbox(self.directory).read_unexpired(invitation_id)
        ciphertext = (self.directory / "invitations" / f"{invitation_id}.invite").read_bytes()
        self.assertFalse(invitation.encode("ascii") in ciphertext)
        self.assertFalse(invitation in issued.text)
        return record, body, invitation

    async def activate(self, invitation, *, headers=None, password=None):
        return await self.client.post("/api/v1/auth/activate", headers=self.headers if headers is None else headers,
                                      json={"invitation": invitation, "password": password or self.password})

    async def test_student_invitation_through_login_refresh_me_and_logout(self):
        health = (await self.client.get("/api/v1/health/db")).json()
        self.assertEqual((health["connected"], health["database"]), (True, "SQLite"))
        student, account, invitation = await self.issue()
        self.assertEqual((await self.login(student["email"])).status_code, 401)
        activated = await self.activate(invitation)
        self.assertEqual(activated.status_code, 204)
        self.assertEqual((await self.activate(invitation)).status_code, 400)
        with self.factory() as db:
            user = db.get(User, UUID(account["user_id"]))
            token = db.get(AccountActionToken, UUID(account["invitation_id"]))
            self.assertEqual((user.account_status, user.auth_version), (AccountStatus.ACTIVE, 1))
            self.assertIsNotNone(token.consumed_at)
            self.assertFalse(user.hashed_password == self.password)
            self.assertTrue(user.hashed_password.startswith("$argon2id$"))

        logged_in = await self.login(student["email"])
        student_headers = self.bearer(logged_in)
        self.assertIn("Secure", logged_in.headers["set-cookie"])
        self.assertIn("HttpOnly", logged_in.headers["set-cookie"])
        me = await self.client.get("/api/v1/auth/me", headers=student_headers)
        self.assertEqual(me.json(), {"id": account["user_id"], "role": "STUDENT", "email": student["email"]})
        self.assertEqual((await self.client.get("/api/v1/admin/demo-roster", headers=student_headers)).status_code, 403)
        self.assertEqual((await self.client.post("/api/v1/admin/students", headers=student_headers,
                                                 json=student)).status_code, 403)
        refreshed = await self.client.post("/api/v1/auth/refresh", headers=self.headers)
        refreshed_headers = self.bearer(refreshed)
        self.assertEqual((await self.client.post("/api/v1/auth/logout", headers=self.headers)).status_code, 204)
        self.assertEqual((await self.client.get("/api/v1/auth/me", headers=refreshed_headers)).status_code, 401)

    async def test_manual_records_assignments_demographics_and_account_deactivation(self):
        headers = self.bearer(await self.login(DEMO_ADMIN_EMAIL))
        base = "/api/v1/admin"

        async def save(method, path, payload, status=201):
            response = await self.client.request(method, base + path, headers=headers, json=payload)
            self.assertEqual(response.status_code, status, response.text)
            return response.json() if response.content and status < 400 else None

        department = {"code": "FAKE", "name": "Fictional Phase One Department", "is_active": True}
        created = await save("POST", "/catalog/departments", department)
        await save("POST", "/catalog/departments", department, 409)
        year = await save("POST", "/catalog/academic-years", {
            "name": "Fictional 2027", "start_date": "2027-01-01", "end_date": "2027-12-31", "is_current": True,
        })
        item = {"name": "Fictional Year One", "department_id": created["id"], "academic_year_id": year["id"],
                "batch": "2027", "semester": 1, "section": "A", "is_active": True}
        first = await save("POST", "/catalog/classes", item)
        second = await save("POST", "/catalog/classes", item | {"name": "Fictional Year One B", "section": "B"})
        await save("PUT", "/catalog/departments/" + created["id"], department | {"is_active": False}, 409)
        student = {"email": "phase-one-student@example.com", "full_name": "Fictional Student",
                   "department_id": created["id"], "class_id": first["id"],
                   "roll_number": "FAKE-01", "register_number": "FAKE-REG-01"}
        record = await save("POST", "/accounts/student", student)
        await save("POST", "/accounts/student", student | {"email": "duplicate-roll@example.com"}, 409)
        users = (await self.client.get(base + "/users", headers=headers)).json()
        saved = next(user for user in users if user["id"] == record["user_id"])
        self.assertEqual((saved["gender"], saved["accommodation"]), (None, None))
        changes = {name: student[name] for name in ("roll_number", "register_number", "full_name")}
        edited = await save("PUT", "/users/" + record["user_id"], changes | {
            "gender": "FEMALE", "accommodation": "OUTSIDE_STAYING",
        }, 200)
        self.assertEqual((edited["gender"], edited["accommodation"]), ("FEMALE", "OUTSIDE_STAYING"))
        enrollment = await save("PUT", "/students/" + record["user_id"] + "/enrollment",
                                {"class_id": second["id"], "is_active": True}, 200)
        self.assertEqual(len(enrollment["enrollments"]), 1)
        self.assertEqual(enrollment["enrollments"][0]["class_id"], second["id"])

        faculty = {"email": "phase-one-faculty@example.com", "full_name": "Fictional Faculty",
                   "department_id": created["id"], "staff_id": "FAKE-F01", "designation": "Lecturer"}
        tutor = await save("POST", "/accounts/faculty", faculty)
        token = DemoInvitationOutbox(self.directory).read_unexpired(UUID(tutor["invitation_id"]))
        self.assertEqual((await self.activate(token)).status_code, 204)
        await save("PUT", "/academics/classes/" + second["id"] + "/tutor", {"tutor_id": tutor["profile_id"]}, 204)
        faculty_edit = {key: value for key, value in faculty.items() if key != "email"}
        await save("PUT", "/users/" + tutor["user_id"], faculty_edit | {"designation": "Senior Lecturer"}, 200)
        tutor_headers = self.bearer(await self.login(faculty["email"]))
        self.assertEqual((await self.client.get(base + "/metrics", headers=tutor_headers)).status_code, 403)
        self.assertEqual((await self.client.post(base + "/catalog/departments", headers=tutor_headers,
                                                 json=department)).status_code, 403)

        hod = await save("POST", "/accounts/hod", {"email": "phase-one-hod@example.com",
                         "full_name": "Original HOD", "department_id": created["id"]})
        await save("PUT", "/users/" + hod["user_id"], {"full_name": "Updated HOD"}, 200)
        await save("POST", "/users/" + hod["user_id"] + "/deactivate", None, 204)
        history = (await self.client.get(base + "/academics/hod-assignments", headers=headers)).json()["departments"]
        mapping = next(row for row in history if row["id"] == created["id"])["history"][0]
        self.assertEqual(mapping["name"], "Original HOD")
        self.assertIsNotNone(mapping["ended_at"])

        administrator = await save("POST", "/accounts/admin", {
            "email": "phase-one-principal@example.com", "full_name": "Fictional Principal",
            "staff_id": "FAKE-A01", "designation": "Principal",
        })
        token = DemoInvitationOutbox(self.directory).read_unexpired(UUID(administrator["invitation_id"]))
        self.assertEqual((await self.activate(token)).status_code, 204)
        principal = self.bearer(await self.login("phase-one-principal@example.com"))
        self.assertEqual((await self.client.get(base + "/metrics", headers=principal)).status_code, 200)

        await save("POST", "/users/" + tutor["user_id"] + "/deactivate", None, 204)
        self.assertEqual((await self.client.get("/api/v1/auth/me", headers=tutor_headers)).status_code, 401)
        metrics = (await self.client.get(base + "/metrics", headers=headers)).json()
        self.assertEqual(metrics["accounts"]["STUDENT"]["PENDING_ACTIVATION"], 1)
        self.assertEqual(metrics["accounts"]["TUTOR"]["DISABLED"], 1)
        self.assertEqual(metrics["accounts"]["HOD"]["DISABLED"], 1)
        self.assertEqual(metrics["accounts"]["ADMIN"]["ACTIVE"], 2)
        self.assertEqual(metrics["departments"]["active"], 2)
        from app.models.admin_audit import AdminAudit
        with self.factory() as db:
            actions = db.scalars(sa.select(AdminAudit.action)).all()
            self.assertTrue({"create", "update", "deactivate"}.issubset(actions))

    def test_admin_upgrade_preserves_existing_sqlite_rows_and_is_idempotent(self):
        with self.factory.begin() as db:
            user = User(role="STUDENT", email="legacy-phase-one@example.com", student_profile=StudentProfile(
                roll_number="LEGACY-01", register_number="LEGACY-REG-01", full_name="Fictional Legacy Student",
                department_id=DEMO_STUDENT.department_id,
            ))
            db.add(user)
        with closing(sqlite3.connect(self.directory / "campus_od.sqlite3")) as legacy:
            before = legacy.execute("SELECT id, email FROM users").fetchall()
            department = legacy.execute("SELECT id, name FROM departments").fetchall()
            student = legacy.execute("SELECT id, roll_number FROM student_profiles").fetchone()
            legacy.execute("DROP TABLE admin_audit")
            for table, field in (("users", "hod_display_name"), ("student_profiles", "gender"),
                                 ("student_profiles", "accommodation"), ("departments", "is_active"),
                                 ("classes", "is_active")):
                legacy.execute(f"ALTER TABLE {table} DROP COLUMN {field}")
            legacy.commit()

        engine = create_demo_engine(self.directory)
        try:
            upgrade_demo_admin(engine)
            upgrade_demo_admin(engine)
            with engine.connect() as upgraded:
                self.assertEqual(upgraded.exec_driver_sql("SELECT id, email FROM users").fetchall(), before)
                self.assertEqual(upgraded.exec_driver_sql("SELECT id, name FROM departments").fetchall(), department)
                self.assertEqual(upgraded.exec_driver_sql("SELECT is_active FROM classes").scalar_one(), 1)
                self.assertEqual(upgraded.exec_driver_sql(
                    "SELECT id, roll_number, gender, accommodation FROM student_profiles",
                ).one(), (*student, None, None))
                self.assertEqual(upgraded.exec_driver_sql("SELECT count(*) FROM admin_audit").scalar_one(), 0)
        finally:
            engine.dispose()

    async def test_hod_activation_mapping_history_and_session_revocation(self):
        hod, account, invitation = await self.issue("hods")
        self.assertEqual((await self.login(hod["email"])).status_code, 401)
        self.assertEqual((await self.activate(invitation)).status_code, 204)
        admin = self.bearer(await self.login(DEMO_ADMIN_EMAIL))
        hod_headers = self.bearer(await self.login(hod["email"]))
        me = await self.client.get("/api/v1/auth/me", headers=hod_headers)
        self.assertEqual(me.json(), {"id": account["user_id"], "role": "HOD", "email": hod["email"]})

        from app.schemas.provisioning import ApprovedHODRecord, HODProvisioningRequest
        from app.services.account_provisioning import AccountProvisioningService, ProvisioningConflictError
        alternate = HODProvisioningRequest(**(hod | {"email": "alternate.hod@example.com"}))
        service = AccountProvisioningService(session_factory=self.factory, deliver_invitation=lambda _: True)
        admin_id = UUID((await self.client.get("/api/v1/auth/me", headers=admin)).json()["id"])
        with self.assertRaises(ProvisioningConflictError):
            service.provision_hod(alternate, approved=ApprovedHODRecord(**alternate.model_dump()),
                                  administrator_id=admin_id)
        with self.factory() as db:
            self.assertIsNone(db.scalar(sa.select(User.id).where(User.email == alternate.email)))

        base = "/api/v1/admin/academics"
        history = (await self.client.get(base + "/hod-assignments", headers=admin)).json()
        current, = history["departments"][0]["history"]
        self.assertEqual(current["id"], account["profile_id"])
        endpoint = f"{base}/departments/{hod['department_id']}/hod"
        payload = {"user_id": None, "expected_assignment_id": current["id"]}
        self.assertEqual((await self.client.put(endpoint, headers=hod_headers, json=payload)).status_code, 403)
        self.assertEqual((await self.client.put(endpoint, headers=admin, json=payload)).status_code, 204)
        self.assertEqual((await self.client.get("/api/v1/auth/me", headers=hod_headers)).status_code, 401)
        self.assertEqual((await self.client.post("/api/v1/auth/refresh", headers=self.headers)).status_code, 401)
        self.assertEqual((await self.client.put(endpoint, headers=admin, json=payload)).status_code, 409)
        payload = {"user_id": account["user_id"], "expected_assignment_id": None}
        self.assertEqual((await self.client.put(endpoint, headers=admin, json=payload)).status_code, 204)
        history = (await self.client.get(base + "/hod-assignments", headers=admin)).json()
        active, ended = history["departments"][0]["history"]
        self.assertIsNone(active["ended_at"])
        self.assertIsNotNone(ended["ended_at"])
        self.assertNotEqual(active["id"], ended["id"])

        for change, restore in (({"account_status": AccountStatus.DISABLED}, {"account_status": AccountStatus.ACTIVE}),
                                ({"role": "TUTOR"}, {"role": "HOD"})):
            hod_headers = self.bearer(await self.login(hod["email"]))
            for values in (change, restore):
                with self.factory.begin() as db:
                    db.execute(sa.update(User).where(User.id == UUID(account["user_id"])).values(**values))
            self.assertEqual((await self.client.get("/api/v1/auth/me", headers=hod_headers)).status_code, 401)
            self.assertEqual((await self.client.post("/api/v1/auth/refresh", headers=self.headers)).status_code, 401)

    async def test_tutor_invitation_can_be_consumed_only_once_concurrently(self):
        tutor, account, invitation = await self.issue("tutors")
        responses = await asyncio.gather(self.activate(invitation), self.activate(invitation))
        self.assertEqual(sorted(response.status_code for response in responses), [204, 400])
        headers = self.bearer(await self.login(tutor["email"]))
        me = await self.client.get("/api/v1/auth/me", headers=headers)
        self.assertEqual(me.json(), {"id": account["user_id"], "role": "TUTOR", "email": tutor["email"]})
        self.assertEqual((await self.client.post("/api/v1/admin/tutors", headers=headers, json=tutor)).status_code, 403)

    async def test_provisioning_requires_admin_demo_mode_and_csrf_and_rejects_extra_fields(self):
        self.assertEqual((await self.client.get("/api/v1/admin/demo-roster")).status_code, 401)
        headers = self.bearer(await self.login(DEMO_ADMIN_EMAIL))
        roster = (await self.client.get("/api/v1/admin/demo-roster", headers=headers)).json()
        student, = roster["students"]
        self.assertEqual((await self.client.post("/api/v1/admin/students", headers={**headers, "Origin": "https://other.example"},
                                                 json=student)).status_code, 403)
        no_csrf = {name: value for name, value in headers.items() if name != "X-CSRF-Protection"}
        self.assertEqual((await self.client.post("/api/v1/admin/students", headers=no_csrf, json=student)).status_code, 403)
        marker = "fictional password that should be redacted"
        rejected = await self.client.post("/api/v1/admin/students", headers=headers, json=student | {"password": marker})
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(marker in rejected.text)
        with patch.object(settings, "ENVIRONMENT", "development"):
            unavailable = await self.client.post("/api/v1/admin/students", headers=headers, json=student)
        self.assertEqual(unavailable.status_code, 404)

    async def test_activation_rejects_bad_origin_csrf_password_expiry_and_purpose(self):
        _, account, invitation = await self.issue()
        self.assertEqual((await self.activate(invitation, headers={"Origin": DEMO_ORIGIN})).status_code, 403)
        self.assertEqual((await self.activate(invitation, headers=self.headers | {"Origin": "https://other.example"})).status_code,
                         403)
        bad = await self.activate(invitation, password="too short")
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(invitation in bad.text)
        token_id = UUID(account["invitation_id"])
        now = datetime.now(timezone.utc)
        for change in (
            {"created_at": now - timedelta(days=2), "expires_at": now - timedelta(days=1)},
            {"purpose": AccountActionPurpose.PASSWORD_RESET},
            {"invalidated_at": now},
            {"auth_version": 5},
        ):
            with self.factory.begin() as db:
                db.execute(sa.update(AccountActionToken).where(AccountActionToken.id == token_id).values(
                    {"created_at": now - timedelta(minutes=1), "expires_at": now + timedelta(hours=1),
                     "purpose": AccountActionPurpose.ACTIVATION, "invalidated_at": None, "auth_version": 0} | change,
                ))
            self.assertEqual((await self.activate(invitation)).status_code, 400)

    async def test_failed_activation_commit_leaves_password_and_invitation_unchanged(self):
        _, account, invitation = await self.issue()

        def fail(_):
            raise SQLAlchemyError("synthetic commit failure")

        sa.event.listen(self.factory, "before_commit", fail)
        try:
            response = await self.activate(invitation)
        finally:
            sa.event.remove(self.factory, "before_commit", fail)
        self.assertEqual(response.status_code, 503)
        self.assertFalse(invitation in response.text)
        with self.factory() as db:
            user = db.get(User, UUID(account["user_id"]))
            self.assertEqual(user.account_status, AccountStatus.PENDING_ACTIVATION)
            self.assertIsNone(user.hashed_password)
            self.assertIsNone(db.get(AccountActionToken, UUID(account["invitation_id"])).consumed_at)
        self.assertEqual((await self.activate(invitation)).status_code, 204)

    def test_operator_bootstrap_refuses_another_admin(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            bootstrap_demo_admin(self.directory, self.password)
        with self.factory() as db:
            self.assertEqual(db.scalar(sa.select(sa.func.count()).select_from(User)), 1)
