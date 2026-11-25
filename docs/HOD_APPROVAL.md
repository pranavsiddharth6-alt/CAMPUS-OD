# HOD approval

## Roles and permissions

- **Student** submits Prior OD, then uses Post OD to open eligible applications and collect GPS and participation evidence for each event day. The application keeps its supporting files and decision history.
- **Tutor** handles applications assigned at submission, decides preliminary reviews, verifies each day's evidence, and re-reviews corrections returned by the HOD.
- **HOD** monitors Prior OD in the assigned department. Final review has a separate queue with private forms, proof, and decision controls.
- **Admin** uses the college-managed invitation process and manages academic assignments. The local demo supports fictional roster prefill and manual fictional records.

A department can have one open HOD assignment, and an HOD can hold one open assignment. Provisioning reserves the initial department assignment while the account awaits activation. Access requires an active HOD account, a valid session, and an open assignment. Admins can end a mapping and assign an eligible HOD in **Academic Assignments**. The system retains the dates and actors for assignment changes and links each HOD decision to the exact assignment under which it was made.

## Option B workflow

1. The student submits Prior OD using event details and distinct dates. The system records the student's department and class tutor at submission.
2. The tutor preapproves, rejects, or requests a correction. Preapproval opens evidence collection on the same application.
3. The student captures GPS in Map OD on each approved event date, then attaches venue and attendance evidence. Legacy applications without a venue pin use the earlier combined upload. The tutor verifies each day or requests corrected evidence. GPS flags remain reviewable and never reject the application by themselves. [Map OD policy](PROJECT_STATUS.md#campus-od-30-phase-4)
4. Once all required days are verified and the original signed OD form is on file, the system moves the record to `UNDER_HOD_REVIEW`. A new application without that form stays under tutor verification while explicit Post OD submission is pending development. Existing signed forms remain available.
5. HOD approval sets `OD_FINALIZED`. HOD rejection sets `REJECTED` and requires remarks. Both keep the prior files and history.
6. HOD correction requires remarks and sets `HOD_CORRECTION_REQUESTED`. The student can revise the description and add supporting documents. The event identity, venue, schedule, and original form stay fixed because the evidence was collected for that event. Resubmission sets `UNDER_TUTOR_CORRECTION_REVIEW`.
7. The tutor can keep verified evidence or reopen specific days for new evidence. Previous reviews and all attempts remain visible. The tutor explicitly forwards the correction to HOD after all days are verified. The HOD then records a new decision.

The application audit records who acted, when, the old and new status, and any remarks. Per-day evidence review history shows each attempt and tutor feedback. These views provide in-app updates for forwarding, decisions, corrections and resubmissions.

### Future Option A

A future policy could use tutor preapproval → HOD approval → participation evidence → tutor final verification. That would change which review opens evidence collection and which decision finalizes OD. The backend owns the transition rules and per-day verification checks. Option B is active.

## API and portals

All paths below are relative to `/api/v1`.

- `GET /hod/dashboard` returns pending, HOD-approved, and HOD-rejected counts.
- `GET /hod/applications?view=pending` lists the current queue. Use `view=history` for applications with HOD decisions, including requests for correction. Each application's full status history remains available on its detail page.
- `GET /hod/applications?view=prior` and `GET /hod/applications/{id}/prior` support read-only monitoring of department applications. The detail response contains event information and status history. It omits documents, participation evidence, and the decision revision.
- `POST /hod/applications/{id}/decision` accepts `action` (`APPROVE`, `REJECT`, or `REQUEST_CORRECTION`), `expected_revision` from the detail response, and `remarks`. Rejection and correction require nonblank remarks. The backend rechecks department authorization, application status, and evidence under a transaction lock. A stale decision returns HTTP 409.
- `GET /applications/{id}`, `GET /applications/{id}/evidence`, `GET /applications/{id}/documents/{document_id}`, and `GET /applications/{id}/evidence/{submission_id}/files/{kind}` serve details and private downloads to authorized participants. File kinds are `venue-photo` and `organizer-proof`.
- `POST /admin/hods` provisions the HOD from the approved local roster and returns an invitation ID for operator handoff. `GET /admin/academics/hod-assignments` lists mappings and history. `PUT /admin/academics/departments/{department_id}/hod` accepts `user_id` (or null to end the current assignment) and the current `expected_assignment_id` (or null when unassigned).

React routes include `/hod/prior-od` for monitoring, `/hod/applications` for final review, and `/hod/history` for decisions. Sign-in and password activation are shared across roles. [Local setup and provisioning](LOCAL_DEMO.md)

## Migration and testing

Revision `0004_hod_approval` extends the role and application status enums, adds the HOD assignment table and partial unique indexes, records the department on applications, and links HOD decisions to existing status history. PostgreSQL enables RLS and revokes client grants on the new table. Role changes and active-account deactivation revoke existing authentication sessions and refresh tokens. Review the SQL offline from `backend`.

```powershell
.\venv\Scripts\python.exe -m alembic upgrade 0003_account_activation:0004_hod_approval --sql
.\venv\Scripts\python.exe -m unittest discover -q
```

The local backend upgrades initialized SQLite demos with additive schema changes at database startup. Older applications keep their existing status, audit, and files. Since the old schema did not snapshot departments, existing rows take the student's department at upgrade time. Existing tutor-finalized records remain historical finalizations. In-progress submissions continue from their recorded status and follow the HOD handoff when the tutor finishes verification. PostgreSQL deployment awaits explicit approval. Revision 0004 has no automated downgrade because it would require removing decision and assignment data and enum values.

From `frontend`, run `node --test tests/*.test.js` and `npm run build`. Use the fictional localhost browser walkthrough to verify provision → activate → submit → preapprove → capture evidence → verify both days → approve as HOD → check the student history after restart. [Browser walkthrough](LOCAL_DEMO.md)

## Current limits

The local admin provisioning UI uses the encrypted invitation outbox for both fictional roster fixtures and manual records. A deployment needs college roster and invitation delivery adapters wired to the provisioning service. Workflow updates are visible in the application and evidence histories. GPS is supporting evidence and the demo does not verify distance from the venue. PostgreSQL migration SQL has been checked offline. Live Supabase application requires approval. [Phase 1 Admin features](PROJECT_STATUS.md#campus-od-30-phase-1)
