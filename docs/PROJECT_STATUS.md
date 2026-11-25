# Campus OD – Project Status

The Student, Tutor, HOD, and Admin features are implemented in the localhost demo. The phase notes below describe the earlier database foundation and its historical verification. See the current workflow, migration status, and deployment limits. [HOD approval guide](HOD_APPROVAL.md)

## Campus OD 3.0 Phase 1

Phase 1 runs in the isolated SQLite demo. **User Management** invites students, faculty, HODs, and administrators, edits their records, manages student enrollments, and disables accounts. Registrar and Principal use individual ADMIN accounts. **College Records** manages departments, classes, and academic years. **Academic Assignments** manages tutors and department HODs. **OD Monitoring** shows application details and history without private documents, evidence, or workflow controls.

Account totals include active, invited, and disabled accounts. The dashboard displays each count separately. Department totals include active and inactive departments. OD metrics count all applications by their current status, including applications associated with disabled accounts.

Student profiles hold current demographic classifications across academic years. Gender is Male, Female, or unclassified. Accommodation is College Hostel, Outside Staying (private hostel, PG, or rented room), Guardian (relative or local guardian), Other, or unclassified. Missing values are stored as null. Historical accommodation by academic year would require a separate design. A student has one enrollment row per academic year. A same-year move updates that row and records the previous class in admin audit history. Existing OD tutor and department ownership stay recorded on the application.

The SQLite demo adds missing columns and the audit table at startup, without resetting existing records. PostgreSQL revision `0005_admin_records` follows `0004_hod_approval`. It adds nullable demographic and HOD display-name fields, department and class activity flags, and an administrative audit table. HOD name edits preserve the names recorded on earlier assignment and decision history. The audit table uses RLS and revokes client grants. Existing department and class rows become active. Review static SQL from the backend directory:

```powershell
.\venv\Scripts\python.exe -B -m alembic upgrade 0004_hod_approval:0005_admin_records --sql
```

Live Supabase was last verified at `0003_account_activation` during Phase 0. Review both pending revisions and rehearse them against disposable PostgreSQL before scheduling a separately approved deployment. The demo uses the existing encrypted invitation outbox. Production roster authorization, invitation delivery, and the COE parser remain deferred.

Admin routes below are under `/api/v1/admin`. Existing fixture provisioning and assignment routes remain available.

- `POST /accounts/{student|faculty|hod|admin}` creates an invited account. A new HOD invitation reserves the initial department assignment.
- `GET /users`, `PUT /users/{id}`, and `POST /users/{id}/deactivate` manage account records. Sign-in email and role stay fixed. Tutor accounts with open OD applications must resolve those applications before deactivation. Deactivating an active account revokes its sessions. HOD deactivation closes the current assignment and retains its history.
- `GET /catalog` and `POST /catalog/{kind}` / `PUT /catalog/{kind}/{id}` manage departments, classes, and academic years. A department can be made inactive once its classes are inactive and its HOD assignment is ended. Selecting a current year clears other current-year flags.
- `PUT /students/{id}/enrollment` assigns, changes, or ends the enrollment in the selected class's academic year.
- `GET /metrics`, `GET /applications`, and `GET /applications/{id}` provide read-only summaries and monitoring. Participant document and evidence routes retain their existing access checks.

The API checks ADMIN role, demo loopback access, and origin and CSRF protections on writes. Changes are audited in the same transaction as the record update. Admin monitoring has no decision permissions.

All 164 backend tests and 12 frontend tests passed, and the production frontend build succeeded. Verification covered a legacy SQLite upgrade, manual account and catalog management, duplicate prevention, assignment and enrollment changes, deactivation, metrics, and read-only OD access. The isolated browser smoke test verified Admin sign-in, database-backed metrics, the student demographic form and demo prefill, college records, and the OD monitoring page. PostgreSQL SQL was generated offline.

## Campus OD 3.0 Phase 2

The Faculty portal has three navigation sections: **Dashboard**, **OD Approval**, and **Reports**. Dashboard shows Total Students, Hostel Students, Outside Staying, and Guardian. Each card shows a total and counts for boys and girls. Where gender is missing, the student contributes to the category total and the dashboard explains why the breakdown can be smaller. An assigned class with no eligible enrollment shows zero counts. Reports is a Phase 7 placeholder. OD Approval retains the existing list, detail, review, and evidence workflow.

`GET /api/v1/tutor/dashboard` returns the authenticated Faculty member's selectable classes and the first class's aggregate statistics, ordered by class name. Pass `class_id` to select a class. The backend requires the `TUTOR` role and checks the active faculty account, tutor assignment, class, department, and current academic year. Valid UUIDs outside that scope return 404, malformed UUIDs return 422, and other signed-in roles receive 403. A faculty member with no current assignments receives an empty class list and null statistics. The response contains no student identifiers or individual demographic values.

Counts come from distinct student profiles with active enrollments matching the class, academic year, and department. Invited, active, and disabled student login accounts count while academically enrolled. Ending an enrollment removes that student from the dashboard. `COLLEGE_HOSTEL` means the college hostel, `OUTSIDE_STAYING` covers private hostels, PGs, and rented rooms, and `GUARDIAN` covers relatives and local guardians. `OTHER` and missing accommodation contribute to Total Students. Only recorded `MALE` and `FEMALE` values contribute to the respective Boys and Girls counts.

Phase 2 uses the Phase 1 schema and calculates counts on request. No new migration is required. The head is `0005_admin_records`. All 165 backend tests and 12 frontend tests passed, along with the production frontend build and `git diff --check`. A fictional SQLite browser smoke test verified class switching, zero counts, missing gender, the existing OD detail view, the Reports placeholder, and the mobile layout and menu at 390 px. Live Supabase validation and Phase 7 report generation and exports remain deferred.

## Campus OD 3.0 Phase 3

Students use **Prior OD** to submit an event name, organizer, venue, category, purpose, and one or more distinct event dates with sessions. Optional invitation and consent documents use existing private storage. The application retains its student owner, tutor and department snapshot, and status history. Faculty use **OD Approval** to preapprove or reject Prior OD with remarks, or request corrections. Preapproval opens compatible participation evidence and the **Post OD** list.

The same application record carries both stages. `POST /api/v1/applications` accepts multipart event details without `original_form`. Existing API clients may still send that validated attachment for compatibility. The new Prior OD screen never asks for it. Application summaries and details report `post_od_eligible` for open evidence states and HOD corrections. Early and rejected Prior OD cannot open or submit participation evidence. Historical evidence stays available to its authorized participants.

HOD **Prior OD Monitoring** uses `GET /api/v1/hod/applications?view=prior` and `GET /api/v1/hod/applications/{id}/prior`. The server uses the HOD's active department assignment and returns event details and status history without private file metadata or decision controls. Final HOD decisions stay restricted to applications in the final queue. Admin monitoring remains read-only.

Until Phase 5, a new application without a signed form can collect and verify evidence, then stays under tutor verification. Both forwarding and final approval check for the signed form, and final approval also requires every event day to be verified. Existing signed and in-progress applications continue through Option B. Completed records and their attachments are preserved.

Phase 3 uses the existing schema and adds no migrations. The repository head is `0005_admin_records`. Map OD is Phase 4. The explicit Post OD submission and required signed-form upload are Phase 5.

All 167 backend tests and 12 frontend tests passed. The production frontend build and `git diff --check` passed. The fictional SQLite browser walkthrough covered a two-date submission, duplicate-date validation, date removal, department HOD read-only monitoring, Faculty preapproval, and the student's Post OD eligibility before and after approval. The 390 px Prior OD form fit without horizontal overflow.

## Campus OD 3.0 Phase 4

**Prior OD** requires an expected venue pin in addition to the written venue. Students can place or move the pin on a Leaflet map or enter venue coordinates. Assigned Faculty can inspect the pin and request a Prior OD correction before approval. The approved pin stays fixed through evidence collection and HOD corrections. Legacy applications without coordinates retain their earlier evidence workflow and show that geographic verification is unavailable.

**Post OD → Open Map OD** opens a separate, single-capture action for each approved event day. The server checks the authenticated owner, application state, approved venue, and event day. The trusted UTC server receipt must fall on the selected date in Asia/Kolkata, starting at 00:00 IST and ending just before the next midnight. Browser timestamps are optional and informational. Existing timestamp columns retain the UTC storage convention and API timestamps include the UTC offset. The browser requests a fresh position only when the student selects Capture location and displays times in IST.

The server computes Haversine distance using a mean Earth radius of 6,371,008.8 metres. **250 m** distance and **100 m** reported accuracy are inclusive defaults configured by `MAP_OD_RADIUS_METRES` and `MAP_OD_MAX_ACCURACY_METRES`. Both checks must pass. Authorized, well-formed captures made on the event date are saved as passed, outside the boundary, poor accuracy, or both. Failed checks stay visible to authorized Faculty and HOD reviewers. Browser GPS and timestamps can be inaccurate or spoofed, so supporting evidence and human decisions remain necessary.

A draft evidence row per event day keeps independent GPS attempts. Within the allowed date and workflow stage, resending the same request ID with the same reading returns the original attempt. The latest passing attempt is selected, or the latest flagged attempt if none passed. A failed retry cannot displace a passing capture. The file submission references the chosen passing attempt without copying it. Later captures do not rewrite that file evidence reference. Pinned applications require a passing capture for each day's file evidence under the temporary Phase 4 integration. GPS checks never change the application status by themselves. The signed-form, tutor-verification, and final HOD gates still apply.

### Phase 4 API and migration

- `POST /api/v1/applications` requires `expected_venue` in the multipart details. Owning Student and assigned Faculty detail views can see the pin. HOD gets the pin at the authorized evidence stage.
- `GET /api/v1/applications/{id}/map-od` provides scoped event-day progress, outcomes, policy thresholds, and capture history. `POST /api/v1/applications/{id}/days/{day_id}/location` accepts the coordinates, positive accuracy, optional browser timestamp, and request ID. Admin and HOD Prior OD monitoring do not expose the capture history.
- Migration `0006_map_od` extends existing application, evidence, and location tables. It adds nullable pins, a draft marker with a unique per-day index, a capture reference, historical results and thresholds, and a unique request key. The SQLite demo adds the same fields at startup. Existing RLS and grants cover the affected tables. No existing records or files are rewritten.

Generate PostgreSQL SQL offline from `backend` before a disposable PostgreSQL rehearsal:

```powershell
.\venv\Scripts\python.exe -B -m alembic upgrade 0005_admin_records:0006_map_od --sql
```

### Basemap and location privacy

Leaflet 1.9.4 renders the optional venue basemap. Vite development uses OpenStreetMap standard tiles by default. A production build needs `VITE_MAP_OD_TILE_URL` and `VITE_MAP_OD_TILE_ATTRIBUTION` for a provisioned provider. An empty URL disables tiles. Tile failure leaves the interactive map and manual coordinate inputs available. A basemap provider can see the browser's IP address and requested map area. Student capture maps render locally without external tiles, including when focused on a captured position. No external geocoder, background location tracking, or public capture URLs are used. Use HTTPS or localhost with browser location permission. [Leaflet documentation](https://leafletjs.com/reference-1.9.4.html) · [OpenStreetMap tile policy](https://operations.osmfoundation.org/policies/tiles/) · [Browser Geolocation specification](https://www.w3.org/TR/geolocation/)

Full Post OD submission and signed-form upload remain Phase 5. Application-level evidence review remains Phase 6. Live Supabase migration and real-device GPS testing remain pending.

All 173 backend tests and 15 frontend tests passed. The production build, `git diff --check`, and offline PostgreSQL SQL generation passed. The localhost browser smoke test used simulated GPS and a local failing tile endpoint. It verified pin selection, Faculty review, approval gating, event-day selection, passing and flagged captures, retry preservation, simulated permission denial, tile fallback, and the 390 px layout.

## Campus OD 2.0 historical notes

**Sri Krishna Arts and Science College (SKASC)**  
*Smart On-Duty Management System*

Last updated November 18, 2026

**Phase 2 — Backend and Database Foundation is COMPLETE.**

**Phase 3 — Authentication and Authorization is NEXT.**

---

## 1. Roadmap Overview

| Phase | Description | Status |
|---|---|---|
| **Phase 1** | Project Initialization & Frontend Foundation (React, Vite, Tailwind, React Router, Shared Portals, FastAPI Baseline) | **Completed** |
| **Phase 2** | Database Architecture, SQLAlchemy 2.0 Models, Alembic Migrations, Private File Storage & Health Probing | **Completed** |
| **Phase 3** | Authentication and Authorization (JWT, password hashing, and STUDENT / TUTOR / ADMIN access) | **NEXT** |
| **Phase 4** | Student OD application submission and authorized upload and download of original signed college OD forms | Planned |
| **Phase 5** | Automatic tutor assignment, preapproval, rejection, correction requests, and final verification | Planned |
| **Phase 6** | Per-day participation evidence, GPS venue proof, and organizer attendance proof | Planned |
| **Phase 7** | Admin management of users, classes, departments, and tutor assignments, plus auditing and oversight | Planned |
| **Phase 8** | Deployment, Docker, Nginx, and production CI/CD | Planned |

The frontend portal screens and backend schema are implemented foundations. Sign-in, role enforcement, student submissions, tutor decisions, evidence verification, and admin management still need end-to-end API implementation.

---

## 2. Phase 2 Implementation Details

### A. Backend and database architecture

- FastAPI provides the API and a dependency for per-request SQLAlchemy sessions. Successful transactions commit, errors roll back, and the session closes in either case.
- SQLAlchemy 2.0 uses pooled `pg8000` connections to the Supabase Session Pooler. FastAPI and Alembic share a TLS context that verifies the server certificate and hostname. The local CA path is configurable through `SUPABASE_CA_CERT_PATH`.
- **19 Core Normalized Entities:**
  1. `users` — Authentication credentials and system roles (`STUDENT`, `TUTOR`, `ADMIN`).
  2. `departments` — Academic departments at SKASC.
  3. `academic_years` — Term spans and current active year flag.
  4. `classes` — Sections and batch cohorts mapped to departments and academic years.
  5. `student_profiles` — Roll numbers, register numbers, student details.
  6. `tutor_profiles` — Staff IDs, designations, faculty contacts.
  7. `admin_profiles` — Academic administration staff records.
  8. `student_class_enrollments` — Student to class mapping per academic year.
  9. `class_tutor_assignments` — Class to designated tutor assignment mapping.
  10. `od_applications` — OD requests with event metadata, dates, and assigned tutor snapshot.
  11. `event_days` — Multi-day OD calendar with day-specific attendance states (`PENDING`, `VERIFIED`, `REJECTED`).
  12. `stored_files` — Metadata for private storage items (key, size, content-type, SHA-256 checksum).
  13. `application_documents` — Supporting files (original signed college OD forms, event invitations).
  14. `evidence_submissions` — Participation evidence links for event days.
  15. `location_captures` — Latitude, longitude, accuracy, timestamps (stored independently from photos).
  16. `evidence_reviews` — Tutor audit remarks and approval decisions per evidence item.
  17. `application_status_history` — Audit records of lifecycle status transitions.
  18. `notifications` — In-app alerts for students and tutors.
  19. `refresh_tokens` — Secure token storage for session management.

### B. Business Rules & Integrity Invariants
- **Assignment consistency.** Enrollments and tutor assignments must use the class's academic year. The existing one-enrollment-per-student and one-tutor-per-class rules apply within each academic year, including inactive rows.
- **Event dates and evidence.** An application has at most one event-day row per date. The database checks date order, positive day counts, and GPS ranges. It does not assume consecutive event days or restrict evidence to one submission per day.
- **Workflow checks.** The submission transaction must require the original signed OD form. The finalization transaction must check the required evidence for each event day. Define reviewer permissions and record retention in the API before exposing those operations.
- **No Approval Certificates:** In accordance with project instructions, digital approval certificates are omitted.
- **Original form preservation.** `application_documents` can link an original signed OD form to private local file metadata. The Phase 4 upload and authorized download endpoints will preserve access to that original file.
- **Independent GPS Storage:** GPS coordinates (`location_captures`) are modeled separately from venue photograph references (`stored_files`).

### C. File Storage Foundation
- **Local Private Storage:** Implemented in `app/services/storage.py`.
- **Integrity:** SHA-256 checksum calculation, unique UUID storage keys, institutional size validation (5MB max).
- **Security.** The storage service keeps files outside frontend static roots. The API must enforce authentication and authorization before serving uploads.

### D. Verified migration and persistence

- Alembic is linked to SQLAlchemy `Base.metadata`. The initial migration was reviewed in offline SQL, applied to Supabase, and verified with `alembic current` as `0001_initial_schema (head)`.
- Live read-only checks verified 19 application tables, 29 foreign keys, 76 indexes (48 explicit and 28 backing constraints), 7 check constraints, and 8 PostgreSQL enum types.
- The controlled persistence test used the existing FastAPI session configuration. It inserted and committed one temporary department, retrieved and verified it in a fresh session, deleted and committed only that exact row, and confirmed its absence in a final fresh session. All test sessions closed. No test data remained.

#### Supabase access settings

- The Supabase Data API was manually disabled in the dashboard. FastAPI is the only application-facing database access path. Direct PostgreSQL connections through pg8000 continue to work. [Supabase Data API settings](https://supabase.com/docs/guides/api/securing-your-api#disable-the-data-api)
- RLS is enabled without policies on all 19 application tables and `alembic_version`. Live checks verified that neither `anon` nor `authenticated` has effective table or column access. The migration revokes grants to those roles and `PUBLIC` on the Campus OD objects. This schema uses UUIDs and creates no sequences.
- FastAPI and Alembic use the same PostgreSQL role. Live verification confirmed that the role owns the tables and retains read and write access. Supabase-managed objects and schema-wide defaults were left in place.

### E. Implemented API endpoints

- `GET /` returns service metadata and database health.
- `GET /api/v1/status` reports API version and project phase.
- `GET /api/v1/health/db` probes PostgreSQL connectivity and reports latency.

---

## 3. Phase 3 — Authentication and Authorization (NEXT)

- Start with FastAPI sign-in against the existing `users` table and verify passwords with bcrypt. Apply college email validation (`@skasc.ac.in`) to account registration.
- Implement the JWT access and refresh token lifecycle and server-side authorization dependencies for `STUDENT`, `TUTOR`, and `ADMIN`.
- Connect the portal sign-in form and test access to the correct role before enabling the OD workflow APIs.
