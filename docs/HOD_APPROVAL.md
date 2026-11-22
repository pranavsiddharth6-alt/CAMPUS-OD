# HOD approval

## Roles and permissions

- **Student** submits an OD application, uploads the original signed form and supporting files, submits GPS and participation evidence for each event day, and follows decisions and correction requests in application history.
- **Tutor** handles applications assigned at submission, decides preliminary reviews, verifies each day's evidence, and re-reviews corrections returned by the HOD.
- **HOD** reviews applications that reached HOD review in the assigned department. The HOD can read student and event details, download private forms and proof, inspect GPS and tutor remarks, and record a decision. Student records, assignments, and submitted content remain read-only in this portal.
- **Admin** uses the college-managed invitation process and manages academic assignments. In the local demo, the Admin UI uses the fictional approved roster.

A department can have one open HOD assignment, and an HOD can hold one open assignment. Provisioning reserves the initial department assignment while the account awaits activation. Access requires an active HOD account, a valid session, and an open assignment. Admins can end a mapping and assign an eligible HOD in **Academic Assignments**. The system retains the dates and actors for assignment changes and links each HOD decision to the exact assignment under which it was made.

## Option B workflow

1. The student submits an OD application and original signed form. The system records the student's department and class tutor at submission.
2. The tutor preapproves, rejects, or requests a correction. Preapproval opens evidence collection.
3. The student uploads browser GPS, a venue photo, and organizer attendance proof for each event day. The tutor verifies each day or requests corrected evidence. An evidence rejection prevents finalization.
4. Once all required days are verified, the system moves the record to `UNDER_HOD_REVIEW`. The pending queue belongs to the assigned department.
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
- `POST /hod/applications/{id}/decision` accepts `action` (`APPROVE`, `REJECT`, or `REQUEST_CORRECTION`), `expected_revision` from the detail response, and `remarks`. Rejection and correction require nonblank remarks. The backend rechecks department authorization, application status, and evidence under a transaction lock. A stale decision returns HTTP 409.
- `GET /applications/{id}`, `GET /applications/{id}/evidence`, `GET /applications/{id}/documents/{document_id}`, and `GET /applications/{id}/evidence/{submission_id}/files/{kind}` serve details and private downloads to authorized participants. File kinds are `venue-photo` and `organizer-proof`.
- `POST /admin/hods` provisions the HOD from the approved local roster and returns an invitation ID for operator handoff. `GET /admin/academics/hod-assignments` lists mappings and history. `PUT /admin/academics/departments/{department_id}/hod` accepts `user_id` (or null to end the current assignment) and the current `expected_assignment_id` (or null when unassigned).

React routes are `/hod/dashboard`, `/hod/applications`, `/hod/history`, and `/hod/applications/{id}`. Sign-in and password activation are shared across roles. [Local setup and provisioning](LOCAL_DEMO.md)

## Migration and testing

Revision `0004_hod_approval` extends the role and application status enums, adds the HOD assignment table and partial unique indexes, records the department on applications, and links HOD decisions to existing status history. PostgreSQL enables RLS and revokes client grants on the new table. Role changes and active-account deactivation revoke existing authentication sessions and refresh tokens. Review the SQL offline from `backend`.

```powershell
.\venv\Scripts\python.exe -m alembic upgrade 0003_account_activation:0004_hod_approval --sql
.\venv\Scripts\python.exe -m unittest discover -q
```

The local backend upgrades initialized SQLite demos with additive schema changes at database startup. Older applications keep their existing status, audit, and files. Since the old schema did not snapshot departments, existing rows take the student's department at upgrade time. Existing tutor-finalized records remain historical finalizations. In-progress submissions continue from their recorded status and follow the HOD handoff when the tutor finishes verification. PostgreSQL deployment awaits explicit approval. Revision 0004 has no automated downgrade because it would require removing decision and assignment data and enum values.

From `frontend`, run `node --test tests/*.test.js` and `npm run build`. Use the fictional localhost browser walkthrough to verify provision → activate → submit → preapprove → capture evidence → verify both days → approve as HOD → check the student history after restart. [Browser walkthrough](LOCAL_DEMO.md)

## Current limits

The local admin provisioning UI uses the demo roster and encrypted invitation outbox. A deployment needs its college roster and invitation delivery adapters wired to the provisioning service. Workflow updates are visible in the application and evidence histories. GPS is supporting evidence and the demo does not verify distance from the venue. PostgreSQL migration SQL has been checked offline. Live Supabase application requires approval.
