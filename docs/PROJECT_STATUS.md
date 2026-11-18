# Campus OD – Project Status

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
